from datetime import datetime, timezone
from typing import Any


GENERATOR_METRICS = (
    "output_power",
    "fuel_consumption_rate",
    "fuel_remaining",
    "engine_temperature",
)

IMPORTANT_PATHS = {
    "environment.wind_speed.value",
    "environment.external_temperature.value",
    "environment.relative_humidity.value",
}


def is_forecastable(path: str) -> bool:
    if path in IMPORTANT_PATHS:
        return True

    return (
        path.startswith("energy.generators[")
        and any(path.endswith(f".{metric}") for metric in GENERATOR_METRICS)
    )


def forecast_interval(path: str) -> int:
    if "wind_speed" in path:
        return 5

    if "relative_humidity" in path:
        return 3600

    if "external_temperature" in path:
        return 60

    if "energy.generators[" in path:
        return 1

    return 60


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.timestamp()


def _iso_timestamp(value: float) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _predict(
    points: list[tuple[datetime, float]],
    future_timestamp: float,
) -> float:
    if not points:
        return 0.0

    if len(points) < 2:
        return points[-1][1]

    x_values = [_timestamp(timestamp) for timestamp, _ in points]
    y_values = [value for _, value in points]

    mean_x = sum(x_values) / len(x_values)
    mean_y = sum(y_values) / len(y_values)

    denominator = sum((x - mean_x) ** 2 for x in x_values)

    if denominator == 0:
        return y_values[-1]

    slope = sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(x_values, y_values)
    ) / denominator

    return mean_y + slope * (future_timestamp - mean_x)


def _apply_limits(path: str, value: float) -> float:
    if "relative_humidity" in path:
        return max(0.0, min(100.0, value))

    if any(
        metric in path
        for metric in (
            "wind_speed",
            "output_power",
            "fuel_consumption_rate",
            "fuel_remaining",
        )
    ):
        return max(0.0, value)

    if "external_temperature" in path:
        return max(-60.0, min(5.0, value))

    if "engine_temperature" in path:
        return max(-20.0, min(95.0, value))

    return value


def build_predictions(
    history: dict[str, list[tuple[datetime, float]]],
    steps: int = 5,
) -> dict[str, Any]:
    generated_timestamp = datetime.now(timezone.utc).timestamp()

    result: dict[str, Any] = {
        "generated_at": _iso_timestamp(generated_timestamp),
        "steps": steps,
        "series": {},
    }

    for path, points in history.items():
        if not points or not is_forecastable(path):
            continue

        interval = forecast_interval(path)
        values = []

        for step in range(1, steps + 1):
            future_timestamp = generated_timestamp + interval * step
            predicted_value = _predict(points, future_timestamp)

            values.append(
                round(
                    _apply_limits(path, predicted_value),
                    2,
                )
            )

        result["series"][path] = {
            "every_seconds": interval,
            "values": values,
        }

    return result