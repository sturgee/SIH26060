from datetime import datetime, timezone
from sqlalchemy import select, func, and_, Integer
from .database import async_session
from .models import TelemetryDocument, TelemetryValue, TelemetryMeasurement
from .time_utils import ensure_utc, iso_utc

# Stable chart metric aliases. The path is also accepted directly by the API.
METRICS = {
    "temperature": ("environment.external_temperature.value", "°C"),
    "humidity": ("environment.relative_humidity.value", "%"),
    "wind": ("environment.wind_speed.value", "km/h"),
    "solar": ("environment.solar_irradiance.value", "W/m²"),
    "generator_power": ("energy.generators[0].output_power", "kW"),
    "generator_load": ("energy.generators[0].load_percent", "%"),
    "generator_temperature": ("energy.generators[0].engine_temperature", "°C"),
    "battery_soc": ("energy.battery.state_of_charge", "%"),
}


def metric_path(metric: str) -> tuple[str, str]:
    if metric in METRICS:
        return METRICS[metric]
    return metric, ""


def choose_bucket_seconds(span_seconds: float, target_points: int = 900) -> int:
    """Pick a proportional aggregation interval for the requested range."""
    if span_seconds <= 0:
        return 1
    raw = max(1, int(span_seconds / target_points))
    choices = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
               3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800]
    return next((x for x in choices if x >= raw), choices[-1])


async def backfill_measurements() -> None:
    """Populate the normalized table once from the existing telemetry archive."""
    async with async_session() as session:
        count = await session.scalar(select(func.count(TelemetryMeasurement.id)))
        if count and count > 0:
            return

        rows = await session.execute(
            select(
                TelemetryDocument.timestamp,
                TelemetryDocument.station_id,
                TelemetryValue.path,
                TelemetryValue.value_number,
            )
            .join(TelemetryValue, TelemetryValue.document_id == TelemetryDocument.id)
            .where(
                TelemetryValue.value_type == "number",
                TelemetryValue.value_number.is_not(None),
                TelemetryValue.path.in_([path for path, _ in METRICS.values()]),
            )
        )
        values = rows.all()
        if not values:
            return

        batch = []
        for timestamp, station_id, path, value in values:
            unit = ""
            for _, (known_path, known_unit) in METRICS.items():
                if path == known_path:
                    unit = known_unit
                    break
            batch.append(TelemetryMeasurement(
                timestamp=timestamp, station_id=station_id, metric=path,
                value=float(value), unit=unit, source="archive"
            ))
            if len(batch) >= 5000:
                session.add_all(batch)
                await session.flush()
                batch.clear()
        if batch:
            session.add_all(batch)
        await session.commit()


async def save_measurements(timestamp, station_id, flattened_values) -> None:
    async with async_session() as session:
        rows = []
        for item in flattened_values:
            if item.get("value_type") != "number" or item.get("value_number") is None:
                continue
            path = item["path"]
            unit = next((u for p, u in METRICS.values() if p == path), "")
            rows.append(TelemetryMeasurement(
                timestamp=timestamp, station_id=station_id, metric=path,
                value=float(item["value_number"]), unit=unit, source="mqtt"
            ))
        if rows:
            session.add_all(rows)
            await session.commit()


async def query_range(metric: str, start: datetime, end: datetime, station_id: str | None = None):
    path, unit = metric_path(metric)
    start = ensure_utc(start)
    end = ensure_utc(end)
    span = max(1.0, (end - start).total_seconds())
    bucket = choose_bucket_seconds(span)

    async with async_session() as session:
        filters = [
            TelemetryMeasurement.metric == path,
            TelemetryMeasurement.timestamp >= start,
            TelemetryMeasurement.timestamp <= end,
        ]
        if station_id:
            filters.append(TelemetryMeasurement.station_id == station_id)

        if bucket <= 1:
            stmt = select(TelemetryMeasurement.timestamp, TelemetryMeasurement.value).where(and_(*filters)).order_by(TelemetryMeasurement.timestamp)
            result = await session.execute(stmt)
            points = [{"timestamp": iso_utc(ts), "value": float(v), "min": float(v), "max": float(v), "avg": float(v), "samples": 1} for ts, v in result.all()]
        else:
            # SQLite epoch bucketing. It preserves min/max/avg while keeping the response small.
            epoch = func.strftime('%s', TelemetryMeasurement.timestamp)
            bucket_expr = (func.cast(epoch, Integer) / bucket) .cast(Integer)
            stmt = select(
                func.min(TelemetryMeasurement.timestamp),
                func.avg(TelemetryMeasurement.value),
                func.min(TelemetryMeasurement.value),
                func.max(TelemetryMeasurement.value),
                func.count(TelemetryMeasurement.id),
            ).where(and_(*filters)).group_by(bucket_expr).order_by(func.min(TelemetryMeasurement.timestamp))
            result = await session.execute(stmt)
            points = [{"timestamp": iso_utc(ts), "value": float(avg), "avg": float(avg), "min": float(mn), "max": float(mx), "samples": int(n)} for ts, avg, mn, mx, n in result.all()]

    return {"metric": metric, "path": path, "unit": unit, "start": iso_utc(start), "end": iso_utc(end), "bucket_seconds": bucket, "points": points}
