"""Causal cold-weather SOC intent, independent from physical charge permission.

The house model already includes all heat pumps. Never add heat-pump watts to
house watts: use the observed pump as corroborating evidence, and the
conservative non-EV house/PV energy envelope to quantify next-day deficit.
"""
from .pricing import valid
from .soc_energy import Battery

POLICY = "winter-cold-load-adequacy-v1"
COLD_C = 2.0
RISK_FRACTION = 0.70


def _temperature(value):
    return float(value) if valid(value) and -45 <= value <= 55 else None


def evaluate(rows, inputs, model, night_end, horizon=None):
    """Return desired 100% only for cold, energy-deficient *future* days.

    No temperature or no closed forecast horizon => no forced target;
    ordinary economic optimizer remains authoritative. The temperature is
    observed as-of the decision or forecast as-of the same decision, not a
    hindsight weather observation. The result is a shadow intent only.
    """
    future = [r for r in rows if r["start"] >= night_end.timestamp()]
    observed = _temperature(inputs.get("outdoor_c"))
    forecast_temperatures = [_temperature(r.get("temperature_c")) for r in future]
    forecast_temperatures = [v for v in forecast_temperatures if v is not None]
    cold_forecast = min(forecast_temperatures, default=None)
    temperature_source = (
        "fresh_outdoor_sensor" if observed is not None and observed <= COLD_C
        else "asof_hourly_weather" if cold_forecast is not None and cold_forecast <= COLD_C
        else "no_cold_evidence"
    )
    cold = temperature_source != "no_cold_evidence"
    hp = inputs.get("heat_pump_w")
    hp = float(hp) if valid(hp) and 0 <= hp <= 25000 else None
    # The PV and household forecasts are already adjusted by their existing
    # calibration. The high-load/low-PV energy stress is intentionally not an
    # invented probability; it defines a conservative shadow reserve intent.
    home_high = sum(r["house_high_kw"] * r["hours"] for r in future)
    home_central = sum(r["house_kw"] * r["hours"] for r in future)
    pv_low = sum(r["pv_low_kw"] * r["hours"] for r in future)
    pv_central = sum(r["pv_ac_kw"] * r["hours"] for r in future)
    net_stress = max(0.0, home_high - pv_low)
    reserve = inputs.get("reserve_soc")
    capacity = (
        max(0.0, Battery(model).available(100) - Battery(model).available(reserve))
        if valid(reserve) and 0 <= reserve <= 95 else None
    )
    complete = (bool(future) and all(valid(r.get("hours")) and r["hours"] > 0 for r in future)
                and (horizon is None or future[-1]["end"] >= horizon.timestamp()))
    deficit = complete and capacity is not None and capacity > 0 and net_stress >= capacity * RISK_FRACTION
    require_full = cold and deficit
    return {
        "policy": POLICY, "status": "cold_deficit" if require_full else
            "no_temperature_asof" if observed is None and cold_forecast is None else
            "insufficient_energy_forecast" if not complete else "ordinary_economic_plan",
        "desired_target_soc_pct": 100 if require_full else None,
        "outdoor_sensor_c": observed,
        "forecast_min_temperature_c": cold_forecast,
        "temperature_source": temperature_source,
        "heat_pump_observed_w": hp,
        "heat_pump_evidence": "running" if hp is not None and hp >= 250 else
            "idle_or_cycling" if hp is not None else "unavailable",
        "heat_pump_already_in_house_load": True,
        "forecast_house_central_kwh": round(home_central, 4),
        "forecast_house_high_kwh": round(home_high, 4),
        "forecast_pv_central_kwh": round(pv_central, 4),
        "forecast_pv_low_kwh": round(pv_low, 4),
        "stress_net_demand_kwh": round(net_stress, 4),
        "usable_battery_above_reference_reserve_kwh": round(capacity, 4) if capacity is not None else None,
        "required_deficit_fraction": RISK_FRACTION,
        "horizon_complete": complete,
        "scope": "shadow_intent_no_actuator_and_no_weather_probability"
    }
