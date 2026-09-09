from datetime import datetime, timezone
from typing import Any


def forecast_interval(path: str) -> int:
    path_lower = path.lower()

    if "wind" in path_lower:
        return 5

    if "relative_humidity" in path_lower or path_lower.endswith(
        ".humidity"
    ):
        return 3600

    if "food." in path_lower:
        return 10800

    if "water." in path_lower or "logistics.fuel" in path_lower:
        return 3600

    if "indoor" in path_lower or "temperature" in path_lower:
        return 30

    if "generator" in path_lower:
        return 1

    if "battery" in path_lower:
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


def _predict(points: list[tuple[datetime, float]], future_time: float) -> float:
    if not points:
        return 0.0

    if len(points) < 2:
        return points[-1][1]

    x_values = [_timestamp(point[0]) for point in points]
    y_values = [point[1] for point in points]

    mean_x = sum(x_values) / len(x_values)
    mean_y = sum(y_values) / len(y_values)

    denominator = sum((x - mean_x) ** 2 for x in x_values)

    if denominator == 0:
        return y_values[-1]

    slope = sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(x_values, y_values)
    ) / denominator

    intercept = mean_y - slope * mean_x
    return slope * future_time + intercept


def _apply_limits(path: str, value: float) -> float:
    path_lower = path.lower()

    if "humidity" in path_lower:
        return max(0.0, min(100.0, value))

    if "state_of_charge" in path_lower:
        return max(0.0, min(100.0, value))

    if any(
        item in path_lower
        for item in (
            "fuel",
            "remaining",
            "consumption_rate",
            "irradiance",
            "visibility",
            "power",
        )
    ):
        return max(0.0, value)

    return value


def build_predictions(
    history: dict[str, list[tuple[datetime, float]]],
    steps: int = 5,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    generated_timestamp = generated_at.timestamp()

    result: dict[str, Any] = {
        "generated_at": _iso_timestamp(generated_timestamp),
        "model": "ordinary_least_squares_linear_regression",
        "steps": steps,
        "series": {},
    }

    for path, points in history.items():
        if not points:
            continue

        interval = forecast_interval(path)
        values = []

        for step in range(1, steps + 1):
            future_timestamp = generated_timestamp + interval * step
            predicted_value = _predict(points, future_timestamp)
            predicted_value = _apply_limits(path, predicted_value)

            values.append(
                {
                    "timestamp": _iso_timestamp(future_timestamp),
                    "value": round(predicted_value, 2),
                }
            )

        result["series"][path] = {
            "interval_seconds": interval,
            "values": values,
        }

    return result