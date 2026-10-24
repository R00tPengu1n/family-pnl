# Implementation Plan: Family P&L

## Overview

Build the Family P&L service described in `SPEC.md`: a FastAPI REST API holding all
business logic, an arq worker for scheduled jobs, and an aiogram 3 Telegram bot that
talks only to the API. Work follows the module build order from the spec
(`identity` → `fx` → `ledger` → `budgets` → `reports` → `worker` → `bot` → `deploy`),
preceded by a foundation phase. Every task is a vertical slice (model, migration,
repository, service, API, tests) small enough for one branch and one PR.

Detailed tasks with acceptance criteria and verification steps: `tasks/todo.md`.

## Architecture Decisions

Decisions below are recorded as ADRs in `docs/adr/` in the task that introduces them.

- **ADR-0001 arq for background jobs.** Async, Redis-based, cron built in, no separate
  broker; fits the async stack better than Celery. Recorded in Task 1.
- **ADR-0002 Layering and dependency direction.** `api` → `services` →
  `repositories`/`domain`; `domain` is pure Python and is the main unit-test target.
  Recorded in Task 1.
- **ADR-0003 Integration test database.** Tests use `TEST_DATABASE_URL` when it is set
  (the PostgreSQL service in CI) and fall back to testcontainers locally. Migrations are
  applied once per session; each test runs inside a transaction that is rolled back.
  Recorded in Task 2.
- **ADR-0004 Household isolation returns 404.** Every repository query is scoped by
  `household_id`; a foreign object is indistinguishable from a missing one. A shared
  test helper checks this for every endpoint. Recorded in Task 7.
- **ADR-0005 Refresh token rotation.** Refresh tokens are stored hashed with a family id;
  reuse of a rotated token revokes the whole family. Recorded in Task 5.
- **ADR-0006 Login rate limiting fails open.** Per-email and per-IP counters in Redis; a
  Redis outage does not block logins. Recorded in Task 6.
- **ADR-0007 Bot authentication.** The bot holds a service secret and exchanges a
  linked Telegram user id for a short-lived user access token (`POST /auth/telegram`).
  The API still applies normal user permissions to every bot request. Recorded in Task 8.
- **ADR-0008 FX conversion rules.** Rates stored as BYN per unit (with NBRB scale
  normalised); cross rates derived via BYN; nearest earlier rate for missing dates;
  last known rate plus a warning when NBRB is unavailable. Recorded in Task 11.
- **ADR-0009 Notifications via an outbox.** Budget alerts and reminders are written to a
  `notifications` table in the same transaction as the triggering change; the worker
  delivers them through the Telegram Bot API and marks them sent. This gives
  "once per threshold per month" through a unique key and survives worker restarts.
  Recorded in Task 19.
- **Money and time.** `Decimal` / `NUMERIC(14, 2)` for amounts, `NUMERIC(18, 8)` for rates,
  one rounding step `ROUND_HALF_UP`; an injected `Clock` everywhere in business code.

## Task List

### Phase 0: Foundation
- [x] Task 1: Project skeleton, tooling and `GET /health`
- [x] Task 2: Database layer, Alembic and integration test fixtures
- [x] Task 3: CI pipeline in GitHub Actions

### Checkpoint 0: Foundation
- [ ] `scripts/check.ps1` green locally, CI green on `main`

### Phase 1: identity
- [x] Task 4: Registration and login (user, household, owner role, JWT)
- [x] Task 5: Refresh token rotation and logout
- [x] Task 6: Login rate limiting in Redis
- [x] Task 7: Invites, members list and the isolation test helper
- [x] Task 8: Telegram linking and bot authentication (API side)

### Checkpoint 1: identity
- [ ] Two users in one household, a third user isolated (404) — covered by tests

### Phase 2: fx
- [x] Task 9: Currency, Money and cross-rate domain
- [x] Task 10: NBRB client with recorded responses
- [x] Task 11: Rate storage, rate service and `GET /fx/rates`

### Checkpoint 2: fx
- [x] Conversion on an arbitrary historical date works, including weekends and NBRB outage

### Phase 3: ledger
- [x] Task 12: Accounts with personal/shared permissions
- [x] Task 13: Categories with a default set per household
- [x] Task 14: Income and expense operations (CRUD, author/owner permissions)
- [x] Task 15: Transfers between accounts with currency conversion
- [x] Task 16: Account balances, operation filters and pagination

### Checkpoint 3: ledger
- [x] Two members record operations in BYN and RUB; balances and filters are correct

### Phase 4: budgets
- [x] Task 17: Budget approval window domain logic
- [ ] Task 18: Budget drafts, limits and owner approval API
- [ ] Task 19: Budget execution, 80% / 100% thresholds and notification outbox

### Checkpoint 4: budgets
- [ ] Window, owner-only approval and thresholds pass fake-clock tests

### Phase 5: reports
- [ ] Task 20: Base currency, display currency and input currency settings
- [ ] Task 21: Period report (totals, by category, member, month, plan vs actual)
- [ ] Task 22: CSV export of a report
- [ ] Task 23: CSV import of operations with per-row errors

### Checkpoint 5: reports
- [ ] Same report shown in two display currencies is consistent; coverage ≥ 85%

### Phase 6: worker
- [ ] Task 24: arq worker setup and daily rate refresh job
- [ ] Task 25: Telegram notification delivery job
- [ ] Task 26: Daily budget approval reminder job

### Checkpoint 6: worker
- [ ] Jobs run against a fake clock and a fake sender; worker starts against local Redis

### Phase 7: bot
- [ ] Task 27: Bot skeleton, API client and `/start` (registration, invite, linking)
- [ ] Task 28: Quick entry message parser
- [ ] Task 29: Quick entry handler with category matching and buttons
- [ ] Task 30: Balance, monthly report and display currency in the bot
- [ ] Task 31: Budget draft, limits and approval in the bot

### Checkpoint 7: bot
- [ ] Bot works against a local API with a real test bot token

### Phase 8: MVP packaging
- [ ] Task 32: Dockerfiles and full Docker Compose stack
- [ ] Task 33: README.md, README.ru.md and architecture diagram
- [ ] Task 34: Final reviews (`sf-review`, github-portfolio-builder) and fixes

### Checkpoint 8: MVP complete
- [ ] All spec success criteria except deployment are met; owner review

### Phase 9: deploy (after MVP, needs owner input)
- [ ] Task 35: VPS provisioning and `docs/deploy.md`
- [ ] Task 36: CD workflow with migrations
- [ ] Task 37: Daily PostgreSQL backups with rotation and restore procedure

### Checkpoint 9: Production
- [ ] Service survives a reboot, backup restored once on a test database

## Git Workflow

- One task — one branch `feature/<module>-<task>` (for example `feature/identity-invites`),
  several small Conventional Commits inside, one PR into `main`.
- Before each commit: `scripts/check.ps1` (ruff, ruff format, mypy strict, pytest with
  coverage ≥ 85%). Merge after green CI and a self-review with `/engineering:code-review`.
- Every bug fix starts with a failing test (`/engineering:debug`, `/agent-skills:test`).

## Parallelization

The plan is executed sequentially in one session: each module builds on the previous
one's models. Safe to parallelise once Phase 3 is done: Task 28 (pure parser) and
Task 17 (pure window logic) have no database dependencies; Task 33 (docs) can start
after Checkpoint 7.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `uv`, Docker and `gh` are not installed on the developer machine | High | Owner installs them before Task 1 (see "Needed from the owner"). Without Docker, integration tests run only in CI. |
| NBRB API format, scale (e.g. 100 RUB) or availability | Med | Task 10 pins recorded responses; scale normalised in the client; fallback to last known rate. |
| Budget window edge cases (short months, time zone, configurable bounds) | Med | Pure domain function with table-driven tests for all month lengths and midnight edges (Task 17). |
| Isolation leak through a forgotten filter | High | Repositories require `household_id`; shared parametrised isolation test for every endpoint. |
| Bot holds a powerful service secret | Med | Secret only exchanges a linked Telegram id for a user token; permissions stay per user; secret in `.env`/GitHub Secrets. |
| Password typed in Telegram chat | Med | Bot registration is passwordless (Telegram-linked); password set later only through the API. |
| Coverage gate 85% slows down late modules | Low | Tests written with each task, not at the end. |
| Duplicate alerts after worker restarts | Med | Outbox with a unique key per (household, category, month, threshold). |

## Open Questions

1. ~~Spec Q1 — account creation from the bot~~ — approved: passwordless `/start`
   registration and invite redemption in the bot (Tasks 8 and 27).
2. ~~Spec Q2 — default input currency per member~~ — approved: per-member setting
   changeable in the bot (Task 20).
3. **Spec Q3 — VPS provider.** Needed only before Phase 9.
4. **`CLAUDE.md` is listed in `.gitignore`.** It stays local and out of the repository.
   Intentional?

## Needed from the owner

- Before Task 1: install `uv`, Docker Desktop and GitHub CLI (`gh auth login`).
- Before Task 27: a test Telegram bot token from @BotFather in `.env`.
- Before Phase 9: VPS choice and access, domain (if the API is public), GitHub Secrets.
