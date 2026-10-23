# 0.6.2

- Strict plan validation also covers orphan legacy sessions; active legacy models remain frozen.
- EV calibration requires continuous observed inactive-to-active sessions.
- PV-to-EV AC flow and common inverter AC limits are accounted per event.
- Review shares the valid/hash/complete-horizon gate and UTC pre-window calculation.
- PV comparison uses common measured intervals; house and PV quality masks are independent.
- 285 synthetic regression tests; observe_only, no actuator adapter.

# 0.6.1

- Archived as-of weather validation, shared EV/battery allocation and charge port limit.
- Separate directional battery limits, invalid/expired proposal revocation.
- Matched PV masks, canonical hashes and correct SOC end timestamps.

# 0.6.0

- Deterministic scenario SOC planner, causal calibrations and local immutable evidence.

# 0.5.9

- Reference table: forecast >=15 kWh maps to 30% SOC.
- Observe-only context of existing automations and proposed 03-05 coordination.
