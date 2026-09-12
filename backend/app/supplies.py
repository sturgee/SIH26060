from typing import Any


def get_number(payload: dict[str, Any], *paths: str) -> float | None:
    for path in paths:
        value: Any = payload

        for key in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)

        if isinstance(value, dict):
            value = value.get("value")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)

    return None


def days_remaining(
    remaining: float | None,
    daily_usage: float | None,
) -> float | None:
    if remaining is None or daily_usage is None or daily_usage <= 0:
        return None

    return round(remaining / daily_usage, 1)


def calculate_supply_forecast(payload: dict[str, Any]) -> dict[str, Any]:
    food = payload.get("food", {})
    water = payload.get("water", {})
    logistics = payload.get("logistics", {})

    food_days = get_number(
        payload,
        "food.estimated_days_remaining",
    )

    water_remaining = get_number(
        payload,
        "water.fresh_water.remaining",
        "water.remaining",
    )
    water_daily_usage = get_number(
        payload,
        "water.daily_consumption",
        "water.consumption.daily",
        "water.fresh_water.daily_consumption",
    )

    fuel_remaining = get_number(
        payload,
        "logistics.fuel.total_remaining",
        "logistics.fuel.remaining",
        "fuel.remaining",
    )
    fuel_daily_usage = get_number(
        payload,
        "logistics.fuel.daily_consumption",
        "logistics.fuel.consumption.daily",
        "energy.fuel_daily_consumption",
    )

    return {
        "food": {
            "days_remaining": food_days,
            "source": "telemetry",
        },
        "water": {
            "days_remaining": days_remaining(
                water_remaining,
                water_daily_usage,
            ),
            "remaining": water_remaining,
            "daily_usage": water_daily_usage,
            "source": "calculated",
        },
        "fuel": {
            "days_remaining": days_remaining(
                fuel_remaining,
                fuel_daily_usage,
            ),
            "remaining": fuel_remaining,
            "daily_usage": fuel_daily_usage,
            "source": "calculated",
        },
    }


def add_supply_forecast(payload: dict[str, Any]) -> dict[str, Any]:
    payload["supply_forecast"] = calculate_supply_forecast(payload)
    return payload


NORMAL_TEMPERATURE = -10.0
FUEL_CONSUMPTION_INCREASE_PER_DEGREE = 0.02


def calculate_temperature_adjusted_fuel_days(
    normal_days: float | None,
    temperature: float,
) -> float | None:
    if normal_days is None or normal_days <= 0:
        return None

    degrees_below_normal = max(
        0.0,
        NORMAL_TEMPERATURE - temperature,
    )

    consumption_factor = (
        1.0
        + degrees_below_normal * FUEL_CONSUMPTION_INCREASE_PER_DEGREE
    )

    return round(normal_days / consumption_factor, 1)


def calculate_fuel_temperature_forecast(
    payload: dict[str, Any],
    temperature: float,
) -> dict[str, Any]:
    forecast = calculate_supply_forecast(payload)
    normal_days = forecast["fuel"]["days_remaining"]

    adjusted_days = calculate_temperature_adjusted_fuel_days(
        normal_days,
        temperature,
    )

    return {
        "temperature": temperature,
        "normal_temperature": NORMAL_TEMPERATURE,
        "normal_days_remaining": normal_days,
        "temperature_adjusted_days_remaining": adjusted_days,
        "consumption_increase_percent": round(
            max(0.0, NORMAL_TEMPERATURE - temperature)
            * FUEL_CONSUMPTION_INCREASE_PER_DEGREE
            * 100,
            1,
        ),
    }