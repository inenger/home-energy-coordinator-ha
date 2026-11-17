"""Causal energy-adequacy SOC intent, independent from physical charge permission.

The house model already includes all heat pumps. Never add heat-pump watts to
house watts: use the observed pump as corroborating evidence, and the
conservative non-EV house/PV energy envelope to quantify next-day deficit.
"""
from .pricing import valid
from .soc_energy import Battery

POLICY = "energy-adequacy-v2"
COLD_C = 2.0
COLD_RISK_FRACTION = 0.70
SEVERE_CENTRAL_DEFICIT_FRACTION = 1.0
SEVERE_STRESS_DEFICIT_FRACTION = 1.25


def _temperature(value):
    return float(value) if valid(value) and -45 <= value <= 55 else None


def evaluate(rows, inputs, model, night_end, horizon=None):
    """Separate deficit-driven and cold-driven *desired* 100% SOC.

    The energy-only rule can trigger at +5°C (or with missing temperature) but
    requires a complete, causal forecast and BOTH a central energy shortage and
    a pessimistic-envelope shortage. Cold lowers the pessimistic threshold,
    while a missing or incomplete energy horizon never triggers this override.
    The result remains a shadow intent, never a physical inverter setpoint.
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
    net_central = max(0.0, home_central - pv_central)
    net_stress = max(0.0, home_high - pv_low)
    reserve = inputs.get("reserve_soc")
    capacity = (
        max(0.0, Battery(model).available(100) - Battery(model).available(reserve))
        if valid(reserve) and 0 <= reserve <= 95 else None
    )
    complete = (bool(future) and all(valid(r.get("hours")) and r["hours"] > 0 for r in future)
                and (horizon is None or future[-1]["end"] >= horizon.timestamp()))
    valid_capacity = capacity is not None and capacity > 0
    severe_shortfall = (complete and valid_capacity and
                        net_central >= capacity * SEVERE_CENTRAL_DEFICIT_FRACTION and
                        net_stress >= capacity * SEVERE_STRESS_DEFICIT_FRACTION)
    cold_shortfall = (complete and valid_capacity and cold and
                      net_stress >= capacity * COLD_RISK_FRACTION)
    require_full = severe_shortfall or cold_shortfall
    status = (
        "insufficient_energy_forecast" if not complete else
        "missing_battery_energy_reference" if not valid_capacity else
        "severe_energy_deficit" if severe_shortfall else
        "cold_deficit" if cold_shortfall else
        "no_temperature_asof" if observed is None and cold_forecast is None else
        "ordinary_economic_plan"
    )
    return {
        "policy": POLICY, "status": status,
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
        "central_net_demand_kwh": round(net_central, 4),
        "stress_net_demand_kwh": round(net_stress, 4),
        "usable_battery_above_reference_reserve_kwh": round(capacity, 4) if capacity is not None else None,
        "cold_required_stress_fraction": COLD_RISK_FRACTION,
        "severe_required_central_fraction": SEVERE_CENTRAL_DEFICIT_FRACTION,
        "severe_required_stress_fraction": SEVERE_STRESS_DEFICIT_FRACTION,
        "central_deficit_to_usable_capacity": round(net_central/capacity, 4) if valid_capacity else None,
        "stress_deficit_to_usable_capacity": round(net_stress/capacity, 4) if valid_capacity else None,
        "cold_condition_met": cold,
        "energy_deficit_condition_met": bool(severe_shortfall),
        "horizon_complete": complete,
        "scope": "shadow_intent_no_actuator_and_no_weather_probability"
    }
