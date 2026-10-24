# ADR-0001: arq for background jobs

- Status: accepted
- Date: 2026-10-24

## Context

The service needs scheduled jobs (daily NBRB rate refresh, daily budget approval
reminders) and asynchronous delivery of Telegram notifications. The API is fully
async (FastAPI, SQLAlchemy async, httpx) and Redis is already part of the stack for
rate limiting and caching. The workload is small: a few households, a handful of jobs
per day, short tasks.

Options considered:

- **Celery** — mature and feature-rich, but synchronous at its core, needs a broker and
  usually a separate beat process; async code has to be wrapped.
- **APScheduler inside the API process** — no extra service, but jobs stop when the API
  restarts or is scaled, and job state is lost.
- **arq** — asyncio-native job queue on Redis with built-in cron, retries and job
  deduplication by id.

## Decision

Use arq. One worker process (`family_pnl.worker.settings.WorkerSettings`) runs both cron
jobs and queued jobs, reusing the async services and repositories of the API.

## Consequences

- Jobs share the same async code paths as the API; no sync/async bridging.
- No new infrastructure beyond the Redis instance already required.
- arq has a smaller ecosystem than Celery (no built-in monitoring UI); job outcomes are
  observed through structured logs.
- Delivery guarantees for notifications come from the database outbox (ADR-0008), not
  from the queue, so losing Redis data does not lose notifications.
