# 0.6.29 · durable background admission and remaining schema writes

## DB-06

The durable analytics worker used the same 250ms local admission deadline and
fast priority as evidence persistence. A valid ongoing local writer could thus
cause a whole partially committed analytic job to retry, despite an independent
durable queue and an unaffected RAM controller. This is separate from real
SQLITE_BUSY/LOCKED, disk I/O errors and the unresolved historical DB-01 causes.

Only durable analytics opts into normal-priority, cancellable local admission.
It retains one original FIFO ticket while waiting, yields to fast evidence
within the existing bounded-burst fairness contract, and checks shutdown at
most every50ms. After250ms the health explicitly reports waiting_writer with
a diagnostic and writer_wait_count. This is not a failed SQL attempt; the job
continues at the original statement after admission instead of restarting its
previously committed work. Pending durable items and original timestamps remain.
Cancellation removes the ticket without a durable ACK or queue deletion; a new
worker reads the original FIFO. Real SQLite timeout remains250ms and actual
SQLite or injected partial failures retain their original retry/degraded path.
No network or analytics computation is moved into a writer scope. A physical
SQLite call already in progress cannot be cancelled by this local admission API.

The quick evidence writer's bounded wait and safety behavior are unchanged.
Normal FIFO fairness and the eight-fast-burst limit are unchanged. This cannot
preempt an ongoing filesystem commit, prove storage latency eliminated, or
promise a finite background completion time under sustained storage failure.
Waiting remains visible; historical counters are not reset.

## Remaining no-op DDL

RAM/control journal, priority, audit, SOC and batch schema entrypoints still
called CREATE IF NOT EXISTS on existing schemas. They now check every required
table/index using SELECT before entering DDL. A missing table/index still runs
the original schema creation path. This removes unnecessary local admission and
executescript scopes, not a claim of measured physical write-byte reduction.

## Validation

Synthetic tests use production Analytics, Store, Gate and persist_batch: a
writer held beyond the former timeout; exactly-once job continuation after a
partial commit; fast evidence priority; cancellation/restart FIFO; true busy
and I/O errors; existing-schema reads while another writer owns the gate; and
missing index/table repair. Existing partial-error rollback and recovery tests
remain. The older analytics local-timeout regression now checks cancellation
and durable replay because ordinary local waiting no longer throws there.

The first candidate test failed because the real RAM schema still requested a
DDL writer before the newly guarded batch table. The test was retained; the
remaining production schema entrypoints were corrected rather than weakening
the assertion. An earlier read-only source inventory attempted rg on an RPi
without rg; the inventory continued using Python. Failed attempts are preserved.

Private recorded-night arithmetic, recorder completeness, scheduling replay and
operational diagnostics stay on the authorized RPi. They are separate from
synthetic tests, public CI, installation and the next full night. Old evidence
is never rewritten. Runtime remains observe_only, no actuator, tariff, reserve,
legacy automation, retention or recorder exclusion changes.
