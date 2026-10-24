# 0.6.4

- Per-phase 25 A shadow budget calibrated from earlier measured night envelopes, with explicit data provenance, current checks and labeled fallback. No actuator or protection claim.
- Retain economically useful requested targets even when an adverse scenario reaches a lower SOC; expose target, attainable SOC and shortfall separately through runtime and card.
- Shared budget for planning and both priority replays; EV priority uses remaining room for battery charging without intentional EV reduction.
- Read-only reconstruction records phase model peaks and limiting reasons. No changes to historical records or the original addon.

# 0.6.3

- Explicit partial-service planning when the desired EV target cannot fit in 03–05; no invented departure or minimum requirement.
- EV priority minimizes worst remaining EV demand before battery regret. Battery priority minimizes household/battery regret before remaining EV demand; EV import costs are separated. Partial variants never claim equal service or measured savings.
- Independent targets for both priority replays, retained deficits and full input/forecast/calibration provenance on rejected plans.
- Distinct operating-state and charger-mode labels; invalid plan no longer misreported as missing forecast. Unknown model outcomes are published as unknown, preserving historical records.
- Read-only RPi reconstruction tool, Python regressions and an executable card rendering check.

# 0.6.2

- Complete Czech architecture, algorithm, operations, data/AI, automation and delivery documentation; persistent project memory and contributor rules. Documentation changes do not alter runtime behavior.
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
