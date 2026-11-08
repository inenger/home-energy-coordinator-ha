# 0.6.27 · standalone context and bounded storage work

## Contract

The priority addon reads no database from the legacy coordinator at runtime.
A one-time SHA-256 checked standalone-context-v1 gzip bundle may import the
historical EV calibration prefix and hourly weather versions. Original times,
nulls, forecast availability and immutable conflicts are preserved. Import is
restart-idempotent and chunked; interrupted imports have no completion receipt.
Future EV calibration appends the addon's own observations, without inventing
inactive edges across a collection gap. Existing battery/history seeds remain
required. Missing calibration stays explicit, never a fabricated capacity.

Do not stop the legacy installation until the private migration has verified
calibration, forecast provenance, fresh independent observations, original
history and current operation. Preserve its database and supported rollback.
Migration at one installation is not proved by synthetic CI or another machine.

## SQLite

Recorder payload comparison takes place outside the writer gate; the receipt
insert and contiguous durable ACK remain transactional. FULL synchronization
is unchanged. The evidence process keeps a transaction-free WAL connection
alive and performs PASSIVE checkpoints in a separate thread. Managed short
connections disable automatic checkpointing so a closing short connection
is not the last WAL connection. A reader can defer checkpoint progress: report
WAL size/frames and degraded state rather than deleting WAL or weakening sync.
Native backup pinning and raw unclean-stopped restore paths are preserved.

Diagnostics distinguish active SQL, Python scope, commit/rollback and close.
These changes remove bounded, reproducible mechanisms; they do not prove the
cause of every past DB-01 timeout or guarantee physical storage latency.
N06-02 and physical control restrictions remain open.

## Write volume

Large latest-state plan/journal previews publish at most every30s; other large
diagnostics every60s. State/error transitions, collection failure and recovery
bypass the cadence. Pending previews remain latest-state and bounded; original
observed_at is retained. Scalar monitors and complete recorder journal chunks
keep their existing paths. No recorder exclude, purge or historical rewrite.

Portable full copies default to21600s, configurable21600–86400s, and are deferred
while the current real time is inside the night window. An hourly default is
removed. This increases the maximum age of a portable snapshot; SQLite durable
evidence and native backups remain separate. Never claim zero RPO.

## Regressions and rejected attempts

Standalone import/hash/conflict/restart, exact EV fit, handover gap and future
exclusion; planner refresh/decision with no legacy runtime database; WAL lifetime
and FULL; active SQL diagnostics; cadence, failure/recovery and latest pending
state; large receipt equality outside gate through confirmed recorder ACK.

Initial synthetic planner fixtures omitted fit_period and the priority_samples
schema required by the production maintenance entrypoint. They produced
calculation_unavailable and were corrected to represent that entrypoint.
These fixture errors were not suppressed or labelled as application fixes.
Native acceptance, exact deployment source, public head/CI and a new complete
night must each be verified separately. No physical actuator is added.

The first full recovery run exposed preview cadence withholding unchanged sibling monitors on an overflow-to-normal transition. Fixed by bypassing cadence for the entire recovery snapshot; the existing real monitor-worker regression remains unchanged. Original failing run retained.

A later recovery run timed out while combining first cold spawn and post-crash spawn in one recovery wait. Separate diagnostic runs recorded successful but slow cold startups; the monitor-crash fixture now establishes the initial ready heartbeat before injecting failure. Its original bounded recovery wait, restart count and delivery assertions are unchanged. The original failure is retained; this is a fixture stage correction, not proof of a repaired production crash.
