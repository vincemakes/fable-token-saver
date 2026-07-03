# Metering & Billing — Behavior Specification

These are the contractual semantics of the metering module. Code that deviates from this spec is defective.

1. **Billing periods are half-open intervals `[periodStart, periodEnd)`.** An event with `timestamp === periodEnd` belongs to the NEXT period. Adjacent periods must never both count the same event.
2. **Invoice totals round once.** Line amounts are computed exactly in milli-cents; the invoice total is the sum of the exact line amounts, rounded to the nearest cent a single time at the invoice level. Per-line rounding is not permitted.
3. **`EventLog.getAll()` returns a snapshot.** Callers may sort, splice, or otherwise mutate the returned array; this must never affect the log's internal state or the result of subsequent calls.
4. **Concurrent credits must all be applied.** `BalanceStore.credit()` may be called concurrently for the same customer; no update may be lost.
5. **Aggregates always reflect the current log.** `UsageAggregator.totalUnitsForPeriod()` must include events added after a previous computation of the same period (late/backdated events are routine).
6. **`periodBreakdown()` is ordered by numeric period, ascending.** Period 10 comes after period 9, not after period 1.

Public API (exported names and signatures) must not change — downstream services import them.
