# 0.6.28 · wallbox authority, settled calibration and bounded writes

## EV sources

Wallbox power and charging status determine observed charging activity and
connection. Tesla/Tessie cable state is retained only as supplementary evidence;
it cannot override the wallbox, establish realtime activity or supply a missing
wallbox current limit. SOC/target remain supplementary vehicle planning inputs.
Unknown/stale wallbox data remains unknown. Zero power alone does not prove
cable disconnection. A positive wallbox power observation proves observed draw,
not a physical watchdog or a verified actuator. HA report times retain their
original meaning; no physical sample time is manufactured.

The RAM journal records wallbox activity with original report provenance and
explicit observed start/stop transitions only between adjacent known frames.
The existing rapid input TTL, two-new-frame recovery, lease deadlines, phase/DC
limits and actual device ownership checks remain in force. Inconsistent wallbox
and inverter phase data may still require fail-closed stop; no cloud fallback or
fabricated instantaneous phase power is introduced to suppress that protection.

No source timestamp suitable for a causal SOC/counter anchor has been confirmed
for every Tessie report. This release therefore does not silently extrapolate
SOC from HA arrival time or count a charging session twice. Missing SOC remains
explicit in planning while the fast controller remains independent of it.

## PLN-01: learned reserve

Policy phase-budget-v2-wallbox-settled-steps uses only historical rows available
at decision time. Large wallbox EV changes identify bounded transition windows.
An adjacent apparent house step in such a window is attributed using settled
before/after endpoints. A simultaneous persistent real house increase remains;
a short independent house peak outside transitions remains unchanged. No
future row may settle an as-of decision. Missing/gapped or unfinished endpoints
are reported, never synthesized as zero measurements.

Short house pulses inside a cross-source EV transition cannot be disproved by
these measurements. Counts of unresolved/pending transition pairs are retained,
and calibration stays an empirical shadow candidate with explicit limitations,
never a verified breaker safety margin. The instantaneous controller does not
use learned reserves as permission to ignore current phase measurements.

Old immutable SOC decisions, original nights and source records are not updated.
New decisions carry the new calibration policy/hash. A change in feasibility is
not automatically an economic benefit or physically verified charging result.

## DB-05: bounded preparation and writer admission

Large immutable row decoding/equality preparation and loss serialization happen
before the writer gate; all optimistic reads are revalidated before any write.
Journal chunks, compression and sequence-specific JSON/zlib payloads are prepared
before the gate; head/cursors are revalidated atomically with enqueue. Conflicts
retry the original evidence, without advancing partial cursors or durable ACK.

Recorder receipt comparison remains outside the gate. Cursor/receipts/ACK are
committed together. Each bounded HTTP publication group persists its earliest
possible attempt time before sending; a crash cannot move the recorder search
lower bound past an original possible receipt. Sent metadata no longer commits
once per HTTP publication. No network operation is inside a writer transaction.

The shared admission gate provides FIFO within priorities and a bounded fast
burst of eight before serving a waiting normal writer. This coordinates the
existing writers; it is not a new database engine or a claim of zero physical
commit latency. Timed-out tickets are removed. Nested ownership remains intact.
FULL durability, WAL keeper, independent PASSIVE checkpoints and the isolated
RAM controller remain unchanged. DB-01 historical causes are not all closed.

## Validation and scope

Synthetic regressions cover conflicting/missing Tessie, wallbox stop/start and
unknown status, real RAM loop independence, source-to-planner limit selection,
EV lag, real coincident house load, independent brief peaks, future exclusion,
from_db and full planner feasibility with immutable sealed original decisions,
chunk preparation outside the gate, durable pre-send attempt bounds, bounded
commit count, ticket timeout cleanup and bounded writer starvation.

The original synthetic counterexample passes on 0.6.27 because it demonstrates
the old flaw; new regressions require the corrected outcome. Private historical
comparisons, failed attempts and native acceptance stay on the authorized RPi.
Local tests, public CI/merge, installation, recorder and native restore evidence
are separate gates. A new whole night is not replaced by synthetic tests.

Source, tests and documentation only in this release; no physical adapter,
reserve/tariff/legacy automation edits, recorder exclusions, retention policy
changes, deletion or historical rewrites. The earlier Influx filter remains a
separate configuration step.

## Preserved first failed candidate run

The first full run reported one failed fault-injection regression: its injector
patched execute, while the batched outbox path now uses executemany. The injector
now covers both and fails after a real first batch insertion; the original
OperationalError, rollback/no cursor/no partial rows and successful retry checks
remain. This is an adapted fault boundary, not a suppressed storage failure.

## Card labels

Final source review added Czech labels for wallbox-observed start/stop and the
power-transition reason in both existing timeline renderers. No scroll, DOM
layout, history loading or physical control behavior changes. The installed
card source and its cache-version reference require their own exact update
and verification; other dashboard resources and configuration are preserved.
