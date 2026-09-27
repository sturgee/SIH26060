"""
Station health/risk monitoring — refactored for clarity, speed, and easy extension.

Design changes from the original:
1. Thresholds are DATA (a config dict), not hardcoded numbers scattered across
   five near-identical functions. Adding/tuning a metric no longer means
   editing function bodies.
2. One generic `evaluate()` function replaces check_fuel/check_power/
   check_structural/check_temperature/check_wind. Less code, one place to fix
   bugs, and it's trivial to add a new metric (just add a config entry).
3. `correlate_risk` is now rule-driven instead of five copy-pasted `if`
   blocks — each rule is a (condition, status, message) tuple, so adding a
   new compound-risk rule is a one-line addition, not a new `if` branch.
4. Status compared via an Enum-like ordering so "worst status wins" logic is
   explicit instead of implied by if/elif order.
"""

from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# 1. Status levels, ordered from best to worst so we can compare them
# ---------------------------------------------------------------------------

STATUS_ORDER = ["OK", "WARNING", "CRITICAL", "SEVERE"]


def worse(a: str, b: str) -> str:
    """Return whichever status is more severe."""
    return a if STATUS_ORDER.index(a) >= STATUS_ORDER.index(b) else b


# ---------------------------------------------------------------------------
# 2. Metric thresholds as config, not code
# ---------------------------------------------------------------------------
# Each metric: a function to compute the raw value from inputs, then
# ascending (value, status) breakpoints. "low_is_bad" flips the comparison
# direction for metrics like fuel, where LOW values are the problem.

@dataclass
class Metric:
    compute: Callable[..., float]
    breakpoints: list  # list of (threshold, status), checked in order
    low_is_bad: bool
    ok_message: str
    warn_message: str
    crit_message: str


METRICS = {
    "fuel": Metric(
        compute=lambda fuel_level_pct: fuel_level_pct,
        breakpoints=[(15, "CRITICAL"), (30, "WARNING")],
        low_is_bad=True,
        ok_message="Fuel levels normal",
        warn_message="Fuel running low",
        crit_message="Fuel critically low — resupply required",
    ),
    "power": Metric(
        compute=lambda power_load, power_capacity: (
            (power_load / power_capacity) * 100 if power_capacity else 0
        ),
        breakpoints=[(75, "WARNING"), (90, "CRITICAL")],
        low_is_bad=False,
        ok_message="Power load normal",
        warn_message="Power load high",
        crit_message="Power load near capacity — risk of overload",
    ),
    "structural": Metric(
        compute=lambda strain_value: strain_value,
        breakpoints=[(500, "WARNING"), (800, "CRITICAL")],
        low_is_bad=False,
        ok_message="Structural integrity normal",
        warn_message="Elevated structural strain detected",
        crit_message="Structural strain dangerously high — inspect immediately",
    ),
    "temperature": Metric(
        compute=lambda temperature_c: temperature_c,
        breakpoints=[(-60, "WARNING")],
        low_is_bad=True,
        ok_message="Temperature within expected range",
        warn_message="Extreme cold — risk to equipment and personnel",
        crit_message="Extreme cold — risk to equipment and personnel",
    ),
    "wind": Metric(
        compute=lambda wind_speed_kmh: wind_speed_kmh,
        breakpoints=[(60, "WARNING"), (100, "CRITICAL")],
        low_is_bad=False,
        ok_message="Wind conditions normal",
        warn_message="High wind — outdoor activity risk",
        crit_message="Severe storm conditions",
    ),
}


def evaluate(metric_name: str, **kwargs) -> dict:
    """Run a single metric's check using its config."""
    m = METRICS[metric_name]
    value = m.compute(**kwargs)

    status = "OK"
    for threshold, level in m.breakpoints:
        crossed = value < threshold if m.low_is_bad else value > threshold
        if crossed:
            status = level  # last one crossed wins (breakpoints are ascending severity)

    message = {"OK": m.ok_message, "WARNING": m.warn_message, "CRITICAL": m.crit_message}[status]

    result = {"status": status, "message": message}
    if metric_name == "power":
        result["usage_pct"] = round(value, 1)
    return result


# ---------------------------------------------------------------------------
# 3. Fuel-days forecast (unchanged logic, kept isolated — see explanation below)
# ---------------------------------------------------------------------------

def forecast_fuel_days(
    fuel_level_pct: float, tank_capacity_liters: float, daily_consumption_liters: float
) -> Optional[float]:
    if daily_consumption_liters <= 0:
        return None
    current_liters = (fuel_level_pct / 100) * tank_capacity_liters
    return round(current_liters / daily_consumption_liters, 1)


# ---------------------------------------------------------------------------
# 4. Cross-domain compound risk — rule table instead of repeated if-blocks
# ---------------------------------------------------------------------------

COMPOUND_RULES = [
    (
        lambda d: d["wind_speed_kmh"] > 80 and d["fuel_level_pct"] < 30,
        "SEVERE",
        "Storm conditions combined with low fuel — resupply and repair access will be difficult",
    ),
    (
        lambda d: d["temperature_c"] < -55
        and d["power_capacity_kw"]
        and (d["power_load_kw"] / d["power_capacity_kw"]) > 0.85,
        "SEVERE",
        "Extreme cold driving high power demand — risk of power system strain",
    ),
    (
        lambda d: d["structural_strain"] > 500 and d["wind_speed_kmh"] > 60,
        "SEVERE",
        "High wind combined with elevated structural strain — inspect station structure",
    ),
]


def correlate_risk(data: dict) -> list:
    alerts = [
        {"status": status, "message": message}
        for condition, status, message in COMPOUND_RULES
        if condition(data)
    ]
    return alerts or [{"status": "NORMAL", "message": "No compounded cross-domain risk detected"}]


# ---------------------------------------------------------------------------
# 5. One call to check everything and get the station's overall status
# ---------------------------------------------------------------------------

def full_station_check(data: dict) -> dict:
    """Runs every metric + compound rules, returns individual results plus
    a single overall status (the worst one seen anywhere)."""
    results = {
        "fuel": evaluate("fuel", fuel_level_pct=data["fuel_level_pct"]),
        "power": evaluate(
            "power", power_load=data["power_load_kw"], power_capacity=data["power_capacity_kw"]
        ),
        "structural": evaluate("structural", strain_value=data["structural_strain"]),
        "temperature": evaluate("temperature", temperature_c=data["temperature_c"]),
        "wind": evaluate("wind", wind_speed_kmh=data["wind_speed_kmh"]),
    }
    results["compound_risks"] = correlate_risk(data)
    results["fuel_days_remaining"] = forecast_fuel_days(
        data["fuel_level_pct"], data["tank_capacity_liters"], data["daily_consumption_liters"]
    )

    overall = "OK"
    for r in results.values():
        if isinstance(r, dict):
            overall = worse(overall, r["status"])
        elif isinstance(r, list):
            for alert in r:
                if alert["status"] != "NORMAL":
                    overall = worse(overall, alert["status"])
    results["overall_status"] = overall
    return results


if __name__ == "__main__":
    sample = {
        "fuel_level_pct": 22,
        "tank_capacity_liters": 10000,
        "daily_consumption_liters": 150,
        "power_load_kw": 92,
        "power_capacity_kw": 100,
        "structural_strain": 520,
        "temperature_c": -58,
        "wind_speed_kmh": 70,
    }
    import json
    print(json.dumps(full_station_check(sample), indent=2))