# ADR-0009: Notifications through a database outbox

- Status: accepted
- Date: 2026-10-24

## Context

Members are notified in Telegram when a budget category reaches 80% and 100% of its limit —
once per threshold, category and month — and the owner gets daily approval reminders. The
event happens inside an API request (recording an expense); delivery talks to Telegram, which
can be slow or down, and the worker can restart at any time.

## Decision

- An event is a row in `notifications` (kind, payload, `dedupe_key`, `created_at`, `sent_at`,
  `attempts`), written **in the same transaction** as the change that caused it. If the expense
  is rolled back, so is the notification; if it commits, the notification exists.
- `dedupe_key` is unique and inserted with `ON CONFLICT DO NOTHING`. For thresholds it is
  `budget_threshold:<budget>:<category>:<threshold>`, so the same threshold is recorded once
  however often it is detected — also after spending drops below and rises again.
- The API never calls Telegram. The worker (Task 25) reads pending rows (`sent_at IS NULL`,
  partial index), sends them to the household's linked members, and marks them sent;
  `attempts` drives retries with backoff.
- Spending is computed at detection time in the budget currency (each expense at its own
  date's rate). If no rate is available at all, the check is skipped with a warning rather
  than failing the expense; the next expense checks again.

## Consequences

- At-least-once delivery: a crash after sending and before marking sent may repeat one
  message. Acceptable for reminders; avoiding it would need Telegram-side idempotency.
- Losing Redis or the worker loses no notifications; they wait in PostgreSQL.
- Old sent rows accumulate; a cleanup job belongs to the worker.
