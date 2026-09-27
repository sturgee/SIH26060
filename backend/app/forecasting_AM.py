import math
from datetime import datetime, timezone
from typing import Any

from .calculations import (
    forecast_exponential_smoothing,
    forecast_linear_regression,
    heat_loss_to_fuel_rate,
    hours_remaining,
    predict_temperature,
    thermal_time_constant,
    wind_chill,
    zone_heat_loss,
)

# Operational metrics allowed for forecasting
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
    "environment.room_temperature.value",  # Added room temperature tracking
    "logistics.fuel.consumption_rate",
}


def is_forecastable(path: str) -> bool:
    """Checks if a given telemetry JSON path should be forecasted."""
    if path in IMPORTANT_PATHS:
        return True

    return path.startswith("energy.generators[") and any(
        path.endswith(f".{metric}") for metric in GENERATOR_METRICS
    )


def forecast_interval(path: str) -> int:
    """Defines prediction step interval (in seconds) per metric type."""
    if "wind_speed" in path:
        return 5

    if "relative_humidity" in path:
        return 3600

    if "external_temperature" in path or "room_temperature" in path:
        return 60

    if "energy.generators[" in path:
        return 1

    if "fuel" in path:
        return 60

    return 60


def _iso_timestamp(value: float) -> str:
    """Formats UNIX epoch timestamps to UTC ISO strings."""
    return (
        datetime.fromtimestamp(value, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _apply_limits(path: str, value: float) -> float:
    """Clamps raw mathematical forecasts to realistic operational bounds."""
    if "relative_humidity" in path:
        return max(0.0, min(100.0, value))

    if any(
        metric in path
        for metric in (
            "wind_speed",
            "output_power",
            "fuel_consumption_rate",
            "fuel_remaining",
            "consumption_rate",
        )
    ):
        return max(0.0, value)

    if "external_temperature" in path:
        return max(-60.0, min(5.0, value))

    if "room_temperature" in path:
        return max(-10.0, min(35.0, value))

    if "engine_temperature" in path:
        return max(-20.0, min(95.0, value))

    return value


def _derive_thermal_fuel_rate(
    history: dict[str, list[tuple[datetime, float]]],
) -> float:
    """
    Uses calculations.py (wind_chill, zone_heat_loss, heat_loss_to_fuel_rate)
    to compute baseline heating fuel usage (L/h) based on external conditions.
    """
    temp_points = history.get("environment.external_temperature.value", [])
    wind_points = history.get("environment.wind_speed.value", [])

    if not temp_points:
        return 0.0

    current_temp = temp_points[-1][1]
    current_wind = wind_points[-1][1] if wind_points else 0.0

    # 1. Compute effective felt temperature on building envelope
    effective_temp = wind_chill(current_temp, current_wind)

    # 2. Estimate heat loss across station envelope (U=0.35 W/m²K, Area=250m², Inside=20°C)
    heat_loss_watts = zone_heat_loss(
        U_value=0.35,
        area_m2=250.0,
        temp_inside_c=20.0,
        temp_outside_c=effective_temp,
        wind_speed_kmh=current_wind,
    )

    # 3. Convert Thermal Loss (Watts) -> Required Diesel Burn Rate (L/h)
    return heat_loss_to_fuel_rate(heat_loss_watts)


def _predict_room_temperature(
    history: dict[str, list[tuple[datetime, float]]],
    steps: int = 5,
    interval_seconds: int = 60,
) -> list[float]:
    """
    Predicts room temperature dynamic progression.
    If heating telemetry is active, uses trend regression.
    In emergency scenario (no heating info), models thermal decay via Newton's Law of Cooling.
    """
    room_points = history.get("environment.room_temperature.value", [])
    ext_points = history.get("environment.external_temperature.value", [])

    # Fallback default if historical room data is missing
    if not room_points:
        return [20.0] * steps

    current_room_temp = room_points[-1][1]
    current_ext_temp = ext_points[-1][1] if ext_points else -15.0

    # Option A: Standard trend-based prediction (if normal operational history exists)
    if len(room_points) >= 3:
        numeric_series = [val for _, val in room_points]
        raw_forecasts = forecast_linear_regression(
            numeric_series, periods_ahead=steps
        )
        if raw_forecasts:
            return [
                round(_apply_limits("room_temperature", val), 2)
                for val in raw_forecasts
            ]

    # Option B: Physical Thermal Decay Model (Newton's Law of Cooling)
    # Station envelope properties: Thermal mass approx = 12,000 kg, specific heat = 1005 J/kg·K
    tau = thermal_time_constant(
        mass_kg=12000.0,
        specific_heat_j_per_kg_k=1005.0,
        U_value=0.35,
        area_m2=250.0,
    )

    decay_predictions = []
    for step in range(1, steps + 1):
        elapsed_sec = step * interval_seconds
        predicted_t = predict_temperature(
            t_start_c=current_room_temp,
            t_env_c=current_ext_temp,
            tau_seconds=tau,
            elapsed_seconds=elapsed_sec,
        )
        decay_predictions.append(
            round(_apply_limits("room_temperature", predicted_t), 2)
        )

    return decay_predictions


def build_predictions(
    history: dict[str, list[tuple[datetime, float]]],
    steps: int = 5,
) -> dict[str, Any]:
    """
    Generates multi-step predictive forecasts across time-series metrics.
    Includes fuel consumption rate and room temperature models.
    """
    generated_timestamp = datetime.now(timezone.utc).timestamp()

    result: dict[str, Any] = {
        "generated_at": _iso_timestamp(generated_timestamp),
        "steps": steps,
        "series": {},
        "derived_insights": {},
    }

    # Process all standard forecastable metrics
    for path, points in history.items():
        if not points or not is_forecastable(path):
            continue

        interval = forecast_interval(path)
        numeric_series = [val for _, val in points]

        # Use linear regression for structural trends
        if any(k in path for k in ("temperature", "fuel_remaining", "output_power")):
            raw_forecasts = forecast_linear_regression(
                numeric_series, periods_ahead=steps
            )
        # Use exponential smoothing for volatile variables
        else:
            raw_forecasts = forecast_exponential_smoothing(
                numeric_series, alpha=0.3, periods_ahead=steps
            )

        if not raw_forecasts:
            raw_forecasts = [numeric_series[-1]] * steps

        values = [round(_apply_limits(path, f), 2) for f in raw_forecasts]

        result["series"][path] = {
            "every_seconds": interval,
            "values": values,
        }

    # =========================================================================
    # Explicit Room Temperature Forecast
    # =========================================================================
    room_interval = forecast_interval("environment.room_temperature.value")
    room_temp_predictions = _predict_room_temperature(
        history=history, steps=steps, interval_seconds=room_interval
    )

    result["series"]["environment.room_temperature.value"] = {
        "every_seconds": room_interval,
        "values": room_temp_predictions,
    }

    # =========================================================================
    # Fuel Consumption Rate & Runway Derivation
    # =========================================================================
    gen_fuel_rates = [
        points[-1][1]
        for path, points in history.items()
        if "generators" in path and "fuel_consumption_rate" in path and points
    ]
    gen_burn_rate = sum(gen_fuel_rates)
    thermal_fuel_rate = _derive_thermal_fuel_rate(history)
    total_fuel_consumption_rate = round(gen_burn_rate + thermal_fuel_rate, 2)

    result["series"]["logistics.fuel.consumption_rate"] = {
        "every_seconds": 60,
        "values": [total_fuel_consumption_rate] * steps,
    }

    fuel_level_points = history.get(
        "logistics.fuel.total_remaining", []
    ) or history.get("fuel.remaining", [])
    current_fuel_level = fuel_level_points[-1][1] if fuel_level_points else None

    runway_hours = None
    if current_fuel_level is not None and total_fuel_consumption_rate > 0:
        runway_hours = hours_remaining(
            current_fuel_level, total_fuel_consumption_rate
        )

    result["derived_insights"]["operational_summary"] = {
        "generator_burn_rate_lph": round(gen_burn_rate, 2),
        "heating_burn_rate_lph": round(thermal_fuel_rate, 2),
        "total_fuel_consumption_rate_lph": total_fuel_consumption_rate,
        "estimated_hours_remaining": runway_hours,
        "projected_room_temp_end_of_window": room_temp_predictions[-1]
        if room_temp_predictions
        else None,
    }

    return result