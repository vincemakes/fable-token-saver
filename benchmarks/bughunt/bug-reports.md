# Open Production Bug Reports

Symptoms only — root causes unknown. Some reports may have more than one underlying cause.

## BR-101 — Invoice totals off by 1-2 cents (Finance, P1)

Finance reconciliation finds our invoice totals disagree with their spreadsheet by one or two cents, but only for customers with many small line items priced at fractions of a cent per unit (e.g. $0.0005/call). Whole-cent-priced customers reconcile exactly.

## BR-102 — Midnight double-billing + backfill not reflected (Billing, P0)

A customer was billed in BOTH the January and February periods for a single API call that happened exactly at the period boundary (midnight, first of the month).

Separately (or maybe related?): when the ingestion queue backfills late events into past periods, the period totals sometimes do not change until the service is restarted, even though the events are visibly in the log.

## BR-103 — Bulk top-ups losing credits (Support, P0)

When the billing UI applies two account credits in quick succession (bulk top-up flow fires them concurrently), the final balance sometimes reflects only one of them. Sequential top-ups from the CLI always work.

## BR-104 — Events out of order after dashboard ships + annual report ordering (Dashboard, P2)

Since the dashboard team shipped the usage chart (which sorts the event list it fetches), invoices occasionally assign events oddly, as if the log itself changed order. Also, unrelated(?): the annual breakdown lists period 10 immediately after period 1, then period 2.
