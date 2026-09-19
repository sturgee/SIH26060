"""
calculations.py — Core math for the station digital twin.

Design principle: every function here is PURE. It takes plain numbers/lists
in and returns plain numbers/dicts out. None of these functions know
anything about your JSON schema (format.json) — that mapping belongs in a
separate adapter layer, so this module stays testable and reusable no
matter how the data format evolves.

Functions marked "TUNE" have a formula that's correct but include a
constant (U-value, k, alpha, weights) your team should calibrate against
real/historical station data rather than trust the defaults blindly.
"""

import math
from datetime import datetime
from typing import Optional, Sequence, Tuple


# ===========================================================================
# 1. Generic "time until depletion" — reused for fuel, water, food, etc.
# ===========================================================================

def days_remaining(current_amount: float, daily_rate: float) -> Optional[float]:
    """
    How many days until `current_amount` hits zero at `daily_rate` consumption.
    Works for fuel (L), water (L), food (kg) — anything with a level + a
    daily burn rate. Returns None if rate is zero/negative (can't deplete,
    or bad data).
    """
    if daily_rate <= 0:
        return None
    return round(current_amount / daily_rate, 1)


def hours_remaining(current_amount: float, hourly_rate: float) -> Optional[float]:
    """Same idea as days_remaining but for hourly rates (e.g. battery, generator fuel tank)."""
    if hourly_rate <= 0:
        return None
    return round(current_amount / hourly_rate, 2)


# ===========================================================================
# 2. Rate of change — reused for pressure trend, health degradation,
#    connectivity backlog growth
# ===========================================================================

def rate_of_change(series: Sequence[Tuple[datetime, float]]) -> Optional[float]:
    """
    Average rate of change per hour across a time-ordered series of
    (timestamp, value) pairs. E.g. pressure trend (hPa/hr), infra health
    decay (%/hr), buffered_messages growth (msgs/hr).

    Uses first-vs-last point (simple slope). Swap in a proper linear
    regression over all points if the series is noisy.
    """
    if len(series) < 2:
        return None
    t0, v0 = series[0]
    t1, v1 = series[-1]
    hours = (t1 - t0).total_seconds() / 3600
    if hours == 0:
        return None
    return round((v1 - v0) / hours, 4)


# ===========================================================================
# 3. Wind chill — effective temperature, also feeds into heat-loss (#5)
# ===========================================================================

def wind_chill(temp_c: float, wind_speed_kmh: float) -> float:
    """
    Environment Canada / NWS wind chill formula (valid for temp <= 10C and
    wind >= 4.8 km/h, which covers Antarctic conditions). Returns "feels
    like" temperature in Celsius.
    """
    if temp_c > 10 or wind_speed_kmh < 4.8:
        return temp_c  # formula not valid/meaningful outside this range
    v_pow = wind_speed_kmh ** 0.16
    return round(
        13.12 + 0.6215 * temp_c - 11.37 * v_pow + 0.3965 * temp_c * v_pow, 1
    )


# ===========================================================================
# 4. Dew point — condensation risk
# ===========================================================================

def dew_point(temp_c: float, relative_humidity_pct: float) -> float:
    """
    Magnus formula approximation. If a zone's temperature is close to its
    dew point, expect condensation (moisture/mold risk) — relevant for
    e.g. the storage zone.
    """
    a, b = 17.27, 237.7
    gamma = (a * temp_c) / (b + temp_c) + math.log(max(relative_humidity_pct, 0.1) / 100)
    return round((b * gamma) / (a - gamma), 1)


# ===========================================================================
# 5. Zone heat loss — the core of task #1 (per-shed/room heating demand)
# ===========================================================================

def zone_heat_loss(
    U_value: float,
    area_m2: float,
    temp_inside_c: float,
    temp_outside_c: float,
    wind_speed_kmh: float = 0,
    k_wind: float = 0.01,
) -> float:
    """
    TUNE: U_value (W/m2*K) and k_wind need calibration per building/zone.

    Heat lost through a zone's envelope, in Watts:
        Q = U_effective * A * (T_in - T_out)
    where U_effective inflates with wind speed to approximate
    infiltration/convective losses (same idea as wind chill, applied to
    a structure instead of skin).

    Feed this the wind-chill-adjusted outside temp (see wind_chill()) for
    a more conservative/realistic estimate.
    """
    U_effective = U_value + k_wind * wind_speed_kmh
    delta_t = temp_inside_c - temp_outside_c
    return round(U_effective * area_m2 * delta_t, 1)


def heat_loss_to_fuel_rate(
    heat_loss_watts: float, heater_efficiency: float = 0.85, fuel_energy_density_mj_per_l: float = 38.6
) -> float:
    """
    TUNE: heater_efficiency and fuel_energy_density depend on your actual
    heating system/fuel type (38.6 MJ/L is a typical diesel figure).

    Converts a zone's heat-loss (Watts) into liters of fuel per hour needed
    to replace that heat, accounting for heater efficiency losses.
    """
    watts_needed = heat_loss_watts / heater_efficiency
    mj_per_hour = (watts_needed * 3600) / 1_000_000
    return round(mj_per_hour / fuel_energy_density_mj_per_l, 3)


# ===========================================================================
# 6. Thermal time constant — "how fast does this zone cool if heating fails"
# ===========================================================================

def thermal_time_constant(mass_kg: float, specific_heat_j_per_kg_k: float, U_value: float, area_m2: float) -> float:
    """
    TUNE: needs a reasonable estimate of the zone's effective thermal mass
    (air + furnishings + structure — often approximated, not measured).

    tau = (m * c) / (U * A), in seconds. Larger tau = the zone holds its
    temperature longer after heating stops. Use with predict_temperature()
    below to answer "how long until storage drops below freezing."
    """
    return round((mass_kg * specific_heat_j_per_kg_k) / (U_value * area_m2), 1)


def predict_temperature(t_start_c: float, t_env_c: float, tau_seconds: float, elapsed_seconds: float) -> float:
    """
    Newton's law of cooling: exponential decay toward ambient temperature.
        T(t) = T_env + (T_start - T_env) * e^(-t / tau)
    """
    return round(t_env_c + (t_start_c - t_env_c) * math.exp(-elapsed_seconds / tau_seconds), 1)


# ===========================================================================
# 7. Generator efficiency
# ===========================================================================

def generator_efficiency(output_power_kw: float, fuel_consumption_rate_lph: float) -> Optional[float]:
    """kWh produced per liter of fuel burned — lets you compare/track generator health over time."""
    if fuel_consumption_rate_lph <= 0:
        return None
    return round(output_power_kw / fuel_consumption_rate_lph, 3)


# ===========================================================================
# 8. Battery runway
# ===========================================================================

def battery_runway(capacity_kwh: float, state_of_charge_pct: float, net_discharge_kw: float) -> Optional[float]:
    """Hours until battery depletes at current net discharge rate."""
    if net_discharge_kw <= 0:
        return None
    available_kwh = capacity_kwh * (state_of_charge_pct / 100)
    return round(available_kwh / net_discharge_kw, 2)


# ===========================================================================
# 9. Weighted multi-criteria risk score — upgrade for correlate_risk
# ===========================================================================

def weighted_risk_score(normalized_metrics: dict, weights: dict) -> float:
    """
    TUNE: weights should sum to 1.0 and reflect what your team decides
    matters most (e.g. fuel/power probably outweigh comms).

    normalized_metrics: {"fuel": 0.8, "power": 0.4, ...} each in [0, 1]
    where 1.0 = maximum risk.
    weights: {"fuel": 0.3, "power": 0.25, ...} matching keys.

    Returns a single 0-1 station risk index.
    """
    total_weight = sum(weights.get(k, 0) for k in normalized_metrics)
    if total_weight == 0:
        return 0.0
    score = sum(normalized_metrics[k] * weights.get(k, 0) for k in normalized_metrics)
    return round(score / total_weight, 3)


def normalize_low_is_bad(value: float, min_ok: float, max_bad: float) -> float:
    """Helper: turn a 'low value = high risk' metric (e.g. fuel %) into a 0-1 risk score."""
    if value >= min_ok:
        return 0.0
    if value <= max_bad:
        return 1.0
    return round((min_ok - value) / (min_ok - max_bad), 3)


def normalize_high_is_bad(value: float, min_ok: float, max_bad: float) -> float:
    """Helper: turn a 'high value = high risk' metric (e.g. power usage %) into a 0-1 risk score."""
    if value <= min_ok:
        return 0.0
    if value >= max_bad:
        return 1.0
    return round((value - min_ok) / (max_bad - min_ok), 3)


# ===========================================================================
# 10. Forecasting — longer-range graphs (task #6)
# ===========================================================================

def forecast_exponential_smoothing(history: Sequence[float], alpha: float = 0.3, periods_ahead: int = 1) -> list:
    """
    TUNE: alpha (0-1) controls responsiveness vs. smoothness — higher alpha
    reacts faster to recent changes but is noisier.

    Simple exponential smoothing, projected forward flat for periods_ahead
    steps (basic version — doesn't model trend/seasonality).
    """
    if not history:
        return []
    smoothed = history[0]
    for value in history[1:]:
        smoothed = alpha * value + (1 - alpha) * smoothed
    return [round(smoothed, 2)] * periods_ahead


def forecast_linear_regression(history: Sequence[float], periods_ahead: int = 1) -> list:
    """
    Fits a straight line to `history` (equally spaced points) via least
    squares, then projects it forward. Better than smoothing when there's
    a clear directional trend (e.g. steadily dropping temps into winter).
    """
    n = len(history)
    if n < 2:
        return []
    x_vals = list(range(n))
    x_mean = sum(x_vals) / n
    y_mean = sum(history) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, history))
    denominator = sum((x - x_mean) ** 2 for x in x_vals)
    slope = numerator / denominator if denominator else 0
    intercept = y_mean - slope * x_mean
    return [round(intercept + slope * (n - 1 + i), 2) for i in range(1, periods_ahead + 1)]


# ===========================================================================
# 11. Data staleness — task #11
# ===========================================================================

def staleness_check(last_sync: datetime, now: datetime, threshold_seconds: float = 3600) -> dict:
    """Flags whether a data source's last update is older than an acceptable threshold."""
    age_seconds = (now - last_sync).total_seconds()
    return {
        "age_seconds": round(age_seconds, 1),
        "stale": age_seconds > threshold_seconds,
    }


# ===========================================================================
# 12. Meltwater energy cost (lower priority — build if time allows)
# ===========================================================================

def meltwater_energy_cost(mass_kg: float, start_temp_c: float = -20, specific_heat_ice=2100, latent_heat_fusion=334000) -> float:
    """
    Energy (kWh) needed to melt `mass_kg` of snow/ice from start_temp_c to
    0C water: warm the ice to 0C, then supply latent heat to melt it.
        Q = m*c*deltaT + m*Lf
    Links your water and fuel systems together (melting water costs fuel).
    """
    warming_j = mass_kg * specific_heat_ice * (0 - start_temp_c)
    melting_j = mass_kg * latent_heat_fusion
    total_kwh = (warming_j + melting_j) / 3_600_000
    return round(total_kwh, 3)


# ===========================================================================
# Thin wrappers — not separate math, just documented one-liners so the
# "12 core functions" story stays discoverable in one place
# ===========================================================================

def resupply_buffer_days(days_remaining_value: Optional[float], days_until_resupply: float) -> Optional[float]:
    """Positive = comfortable margin before resupply, negative = will run out first."""
    if days_remaining_value is None:
        return None
    return round(days_remaining_value - days_until_resupply, 1)


def per_capita_rate(total_rate: float, personnel_count: int) -> Optional[float]:
    if personnel_count <= 0:
        return None
    return round(total_rate / personnel_count, 2)


def load_ratio_pct(load: float, rated_capacity: float) -> float:
    return round((load / rated_capacity) * 100, 1) if rated_capacity else 0.0
