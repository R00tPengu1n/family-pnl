# Spec: Family P&L

## Objective

Family P&L is a service for tracking a family's shared finances. Each family
member records their own income and expenses from their own account; all members
of the family see the common picture: balances, spending by category, income and
spending per member, and budget execution.

The service runs permanently on a server. People interact with it through a
Telegram bot; the bot is a client of a REST API that holds all business logic.

### Users

- **Family members** — 2+ adults who share a budget. They add operations in
  different currencies (one mostly in BYN, another in RUB, sometimes USD) and
  want to see totals in one currency of their choice.
- **Owner** — the family member who manages members and approves the monthly
  budget.

### Capability map

| Module id | Responsibility | Depends on |
|---|---|---|
| `identity` | Users, auth (JWT), households, roles, invites, Telegram linking | — |
| `ledger` | Accounts, categories, operations (income, expense, transfer) | identity |
| `fx` | Currencies, NBRB rates, historical rate storage, conversion | — |
| `budgets` | Monthly budgets, approval window, limits, alerts | identity, ledger, fx |
| `reports` | Period reports, CSV import/export | ledger, fx, budgets |
| `worker` | Scheduled jobs: rate refresh, budget reminders, alerts | fx, budgets, identity |
| `bot` | Telegram client over the REST API | REST API only |
| `deploy` | VPS deployment, CD, backups | everything |

Build order: `identity` → `fx` → `ledger` → `budgets` → `reports` → `worker` →
`bot` → `deploy`. Each module is delivered as a vertical slice: model, migration,
service, repository, API, tests.

### Functional requirements and acceptance criteria

#### identity

- Registration with email and password (argon2 hash). Login returns an access
  token (15 min) and a refresh token (30 days, rotated on use).
- Login attempts are rate-limited (5 failed attempts per 15 minutes per email
  and per IP).
- A new user gets their own empty household and is its owner.
- The owner creates a one-time invite code valid for 48 hours. A user who
  redeems it becomes a `member` of that household.
- Roles: `owner`, `member`. One household per user in MVP.
- **Isolation:** any request for an object of another household returns 404
  (never 403), so the existence of foreign data is not revealed. Every endpoint
  has a test for this.
- Telegram linking: the user requests a one-time code (10 min) in the API and
  sends it to the bot; the bot binds the Telegram account to the user.

#### fx

- Supported currencies: RUB, BYN, USD.
- Source: National Bank of the Republic of Belarus API (rates to BYN; RUB and
  USD are quoted against BYN, cross rates are derived).
- The current rate is refreshed once a day by a scheduled job.
- Historical rates are fetched on demand and stored permanently (they never
  change). If there is no rate for a date (weekend/holiday), the nearest
  earlier rate is used.
- If the API is unavailable, the last known rate is used and a warning is
  logged.
- Conversion uses the rate **on the date of the operation**.

#### ledger

- Accounts: personal (visible to the household, editable by the creator and the
  owner) or shared; type `card | cash | savings`; currency; balance computed
  from operations.
- Categories: income and expense; a default set is created with each household;
  members can add their own.
- Operations: `income`, `expense`, `transfer` (between accounts, possibly with
  currency conversion). Fields: amount, currency, date, category, account,
  comment, author.
- An operation keeps its original amount and currency.
- An operation can be edited or deleted by its author or the owner.
- Lists support pagination and filters: period, category, account, member,
  currency.

#### budgets

- A budget is a set of monthly limits per expense category in the household's
  base currency.
- Statuses: `draft` → `approved`.
- Approval window for the **next** month: from day 20 to day 30 of the current
  month (in shorter months — to the last day). Window bounds are configurable.
- Inside the window any member can add and change draft limits; only the owner
  approves.
- Outside the window and during the approved month only the owner can change
  the budget.
- While next month's budget is not approved, the owner gets a daily Telegram
  reminder. If the window ends without approval, reminders continue and the
  budget is marked as not approved.
- During the month: remaining amount per category; members are notified when a
  category reaches 80% and 100% of its limit (once per threshold per month).
- All dates and the window are evaluated in the household time zone (default
  `Europe/Minsk`).

#### reports

- Household base currency: RUB by default, changeable by the owner.
- Display currency: each member can choose RUB, BYN or USD for themselves;
  reports and balances use it.
- Report for a period: totals, breakdown by category, by member, by month;
  plan vs actual for budgets.
- CSV import of operations (format documented in README) with per-row
  validation errors; CSV export of a report.

#### bot

- Quick entry: `кофе 5.50`, `такси 300 rub`, `+зарплата 2500 byn` — amount,
  optional currency (defaults to the member's usual input currency), category
  matched by name or chosen with buttons.
- Balance, monthly report, switching display currency.
- Budget draft: view, add/change limits in the window, approve (owner).
- Receives reminders and limit alerts.
- Talks only to the REST API, never to the database.

#### deploy (after MVP)

- API, bot, worker, PostgreSQL and Redis run on a VPS in Docker Compose and
  restart automatically.
- Automatic deploy from GitHub Actions with migrations.
- Daily PostgreSQL backup with rotation and a documented restore procedure.
- Only required ports are exposed; if the API is public, only via HTTPS.
- `docs/deploy.md` describes deploying from scratch.

### Out of scope (MVP)

Web frontend, bank integrations, receipt recognition, mobile app, multiple
households per user.

## Tech Stack

- Python 3.12+
- FastAPI, Pydantic v2, pydantic-settings
- PostgreSQL 16, SQLAlchemy 2.0 (async, asyncpg), Alembic
- Redis 7: scheduler queue, rate limiting, cache
- arq: background jobs and cron (async, Redis-based; decision recorded in ADR)
- aiogram 3: Telegram bot; httpx: HTTP client (bot → API, API → NBRB)
- argon2-cffi, PyJWT
- structlog: structured JSON logs
- Tooling: uv (dependencies and lock file), ruff, mypy (strict), pytest,
  pytest-asyncio, pytest-cov, testcontainers or a CI PostgreSQL service,
  pre-commit, pip-audit
- Docker (multi-stage), Docker Compose, GitHub Actions

## Commands

```bash
# Install dependencies (including dev)
uv sync

# Run the whole stack locally
docker compose up --build

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"

# Run services without Docker
uv run uvicorn family_pnl.api.main:app --reload
uv run python -m family_pnl_bot
uv run arq family_pnl.worker.settings.WorkerSettings

# Quality checks
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=85
uv run pip-audit

# All checks at once (Windows, writes a report to .reports/check.log)
.\scripts\check.ps1
```

## Project Structure

```
src/
  family_pnl/
    core/           → config, logging, security (hashing, JWT), error types
    domain/         → pure business rules: money, currencies, budget window,
                      permissions — no FastAPI, no SQLAlchemy
    models/         → SQLAlchemy models
    repositories/   → database access, one repository per aggregate
    services/       → use cases: orchestrate repositories and domain rules
    integrations/   → external APIs (NBRB client)
    api/            → FastAPI app, routers, dependencies, request/response schemas
    worker/         → arq settings and jobs
  family_pnl_bot/   → aiogram bot: handlers, keyboards, API client, parser
migrations/         → Alembic migrations
tests/
  unit/             → domain and service logic, no database
  integration/      → API tests against real PostgreSQL
  bot/              → message parser and handlers with a mocked API client
docs/
  adr/              → architecture decision records
  deploy.md         → deployment guide
scripts/            → developer scripts (check.ps1, backup)
```

Dependency direction: `api` → `services` → `repositories`/`domain`;
`domain` imports nothing from the project except `core`. The bot imports nothing
from `family_pnl`.

## Code Style

- ruff (lint + format), line length 100, mypy strict for `src/`.
- Type hints everywhere; no `Any` without a reason.
- Money is `Decimal` in code and `NUMERIC(14, 2)` in the database; rates are
  `NUMERIC(18, 8)`. Rounding happens once, at the end of a calculation,
  `ROUND_HALF_UP` to 2 decimal places. `float` is never used for money.
- Time is stored in UTC (`timestamptz`); operation dates are calendar dates in
  the household time zone.
- Errors: domain errors are subclasses of `DomainError` and are mapped to one
  JSON error format in the API.
- Code, comments, commits and docs in English; README additionally in Russian.

```python
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from family_pnl.domain.currency import Currency

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def convert(self, rate: Decimal, target: Currency) -> "Money":
        """Convert using `rate` = units of `target` per one unit of `self.currency`."""
        if self.currency is target:
            return self
        return Money((self.amount * rate).quantize(CENT, ROUND_HALF_UP), target)
```

## Testing Strategy

- pytest + pytest-asyncio; coverage gate 85% in CI.
- **Unit** (`tests/unit`): money and rounding, cross rates, nearest-earlier
  rate, budget window for every month length and time zone edge, permission
  rules, bot message parser. Fast, no I/O.
- **Integration** (`tests/integration`): every endpoint through httpx against a
  real PostgreSQL with migrations applied; household isolation (404) and role
  checks for each endpoint; NBRB client against recorded responses.
- **Worker**: jobs called directly with a fake clock and a fake Telegram sender.
- Time is injected (a `Clock` dependency), never read directly in business code,
  so window and reminder logic is deterministic in tests.
- Bug fixes start with a failing test.

## Boundaries

- **Always:** keep `main` green; small commits in Conventional Commits; a test
  with each feature; migrations for every schema change; validate all input;
  record non-obvious decisions in `docs/adr`; keep secrets out of the repo.
- **Ask first:** changes to MVP scope; adding a paid service; anything
  irreversible on the server or in production data.
- **Never:** commit secrets or `.env`; use `float` for money; skip or delete
  failing tests to get green CI; lower the coverage gate; let the bot access
  the database directly; write "pet project", "educational" or invented users
  and metrics in the repository.

## Success Criteria

- All functional requirements above have passing tests; coverage ≥ 85%.
- CI is green: ruff, mypy strict, pytest with PostgreSQL, Docker build,
  pip-audit.
- `docker compose up` starts API, bot, worker, PostgreSQL and Redis; the API
  answers `GET /health` and serves OpenAPI docs with examples.
- Two Telegram users in one household can record operations in different
  currencies and both see the same monthly report in the currency each chose.
- A third user registered independently sees none of that household's data.
- The budget window, owner-only approval and daily reminders behave as
  specified (covered by tests with a fake clock).
- The service is deployed on a VPS, survives a server reboot, and has daily
  backups.
- README.md (English) and README.ru.md (Russian) describe the project,
  architecture diagram, setup, configuration, deployment and limitations.

## Open Questions

1. **How a member creates an account.** There is no web frontend, so
   email/password registration is only reachable through the API docs page.
   Proposal: registration and invite redemption also work from the bot
   (`/start` → create account linked to Telegram; email and password can be
   added later for API access). The bot deletes any message containing a
   password right after reading it.
2. **Default input currency per member** (BYN for one member, RUB for another)
   so that `кофе 5.50` needs no currency suffix. Proposal: a per-member setting,
   changeable in the bot.
3. **VPS provider** — to be chosen by the owner before the deploy module;
   2–3 options payable from Belarus will be proposed then.
