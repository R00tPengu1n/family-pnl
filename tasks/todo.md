# Task List: Family P&L

Plan and decisions: `tasks/plan.md`. Spec: `SPEC.md`.

**Standard verification for every task** (in addition to the task's own checks):

- [ ] `.\scripts\check.ps1` passes (ruff, ruff format, mypy strict, pytest, coverage ≥ 85%)
- [ ] New migrations upgrade and downgrade cleanly (`uv run alembic upgrade head`,
      `uv run alembic downgrade -1`, `uv run alembic upgrade head`)
- [ ] Every new endpoint has an isolation test (foreign household → 404) and role tests
- [ ] CI green on the PR; self-review done; merged into `main`

---

## Phase 0: Foundation

### Task 1: Project skeleton, tooling and `GET /health`

**Description:** Create the `uv` project with the `src/` layout from the spec, tool
configuration and the minimum running API. Includes `core/config.py` (pydantic-settings),
`core/logging.py` (structlog JSON), `core/clock.py` (`Clock` protocol, system and fake
clocks), `core/errors.py` (`DomainError` hierarchy + one JSON error format handler),
`GET /health`, `scripts/check.ps1`, pre-commit, `.env.example`, ADR-0001 and ADR-0002.
Wires the tools from `CONSTRAINTS.md`: import-linter contracts, `check.ps1 -Stage
fast|task|full`, pre-commit hooks (ruff, gitleaks, floor guard), a Claude Code
post-edit hook running the fast stage, and `.gitattributes` with LF line endings.

**Acceptance criteria:**
- [x] `uv sync` installs everything from the lock file; `pyproject.toml` configures ruff
      (line 100), mypy strict, pytest (coverage gate 85%, branch coverage) and import-linter
- [x] `check.ps1 -Stage fast` ≤ 10 s and `-Stage task` ≤ 90 s, as in `CONSTRAINTS.md`
- [x] `GET /health` returns `200 {"status": "ok"}`; `/docs` serves OpenAPI
- [x] A raised `DomainError` subclass is returned in the common error format

**Verification:**
- [x] `uv run pytest tests/unit tests/integration/test_health.py`
- [x] Manual: `uv run uvicorn --factory family_pnl.api.main:create_app --reload`, open `/health` and `/docs`

**Dependencies:** None
**Files likely touched:** `pyproject.toml`, `uv.lock`, `src/family_pnl/core/*`,
`src/family_pnl/api/main.py`, `scripts/check.ps1`, `.pre-commit-config.yaml`,
`docs/adr/0001-*.md`, `docs/adr/0002-*.md`, `tests/...`
**Estimated scope:** M

### Task 2: Database layer, Alembic and integration test fixtures

**Description:** Async SQLAlchemy engine and session dependency, declarative base with
naming conventions, Alembic configured for async and autogenerate,
`docker-compose.dev.yml` with PostgreSQL 16 and Redis 7, and pytest fixtures that apply
migrations once and roll back each test (ADR-0003). `GET /health` also checks the database.

**Acceptance criteria:**
- [x] `docker compose -f docker-compose.dev.yml up -d` starts PostgreSQL and Redis
- [x] `alembic upgrade head` works on an empty database; an empty initial migration exists
- [x] Integration tests use `TEST_DATABASE_URL` or testcontainers and are isolated per test

**Verification:**
- [x] `uv run pytest tests/integration`
- [x] Manual: stop PostgreSQL → `/health` reports the database as unavailable

**Dependencies:** Task 1
**Files likely touched:** `src/family_pnl/core/db.py`, `src/family_pnl/models/base.py`,
`migrations/*`, `alembic.ini`, `docker-compose.dev.yml`, `tests/conftest.py`,
`docs/adr/0003-*.md`
**Estimated scope:** M

### Task 3: CI pipeline in GitHub Actions

**Description:** Workflow on push and PR: `uv sync --locked`, ruff check, ruff format
check, mypy, lint-imports, floor guard (`fetch-depth: 0`), pytest with a PostgreSQL 16
service and Redis, coverage gate, pip-audit, Semgrep, gitleaks (`--redact`), and mutmut
on PRs touching `src/family_pnl/domain/`. Docker build is added to CI in Task 32.
Record the first measured coverage in `CONSTRAINTS.md` (Measured, not yet enforced).

**Acceptance criteria:**
- [x] Workflow runs on PRs into `main` and on pushes to `main`
- [x] Every row of `CONSTRAINTS.md` marked "CI" fails the job when violated
- [x] Branch protection on `main` requires the CI check (enabled 2026-10-24: six required checks, no force push or deletion, admins included)

**Verification:**
- [x] The PR for this task shows a green CI run

**Dependencies:** Task 2
**Files likely touched:** `.github/workflows/ci.yml`
**Estimated scope:** S

### Checkpoint 0: Foundation
- [ ] `scripts/check.ps1` green locally, CI green on `main`
- [ ] Owner confirms the toolchain works on the Windows machine

---

## Phase 1: identity

### Task 4: Registration and login

**Description:** Models `User`, `Household`, `Membership(role)` and migration;
argon2 hashing and JWT helpers in `core/security.py`; `POST /auth/register` creates a user,
an empty household and an owner membership in one transaction; `POST /auth/login` returns
an access token (15 min) and a refresh token (30 days); `GET /me` via a `current_user`
dependency.

**Acceptance criteria:**
- [x] Registration with a duplicate email returns 409; weak/invalid input returns 422
- [x] Login with a wrong password returns 401 without revealing whether the email exists
- [x] `GET /me` returns the user with household and role; an expired token returns 401

**Verification:**
- [x] `uv run pytest tests/unit/test_security.py tests/integration/test_auth.py`

**Dependencies:** Task 2
**Files likely touched:** `models/identity.py`, `repositories/users.py`,
`services/auth.py`, `core/security.py`, `api/routers/auth.py`, migration, tests
**Estimated scope:** M

### Task 5: Refresh token rotation and logout

**Description:** Store refresh tokens hashed with a family id; `POST /auth/refresh`
rotates the token; reuse of a rotated token revokes the family; `POST /auth/logout`
revokes the current token (ADR-0005).

**Acceptance criteria:**
- [x] Refresh returns a new pair and invalidates the old refresh token
- [x] Reusing an old refresh token returns 401 and revokes all tokens of that family
- [x] Token expiry uses the injected clock

**Verification:**
- [x] `uv run pytest tests/integration/test_auth_refresh.py`

**Dependencies:** Task 4
**Files likely touched:** `models/identity.py`, `repositories/refresh_tokens.py`,
`services/auth.py`, `api/routers/auth.py`, migration, `docs/adr/0005-*.md`, tests
**Estimated scope:** M

### Task 6: Login rate limiting in Redis

**Description:** Redis client dependency; count failed logins per email and per IP in a
15-minute window; the 6th attempt returns 429 with `Retry-After`; a successful login does
not reset the IP counter.

**Acceptance criteria:**
- [x] 5 failed attempts per email or per IP within 15 minutes → next attempt 429
- [x] Counters expire after the window (tested with a fake clock or Redis TTL)

**Verification:**
- [x] `uv run pytest tests/integration/test_login_rate_limit.py`

**Dependencies:** Task 4
**Files likely touched:** `core/redis.py`, `services/rate_limit.py`, `api/routers/auth.py`, tests
**Estimated scope:** S

### Task 7: Invites, members list and the isolation test helper

**Description:** `POST /household/invites` (owner) creates a one-time code valid for 48 h;
`POST /household/invites/{code}/redeem` moves a user with an empty own household into the
inviting household as `member`; `GET /household/members`. Introduce the reusable
isolation/role test helper and ADR-0004.

**Acceptance criteria:**
- [x] Member cannot create invites (403 for own household action); code is single-use
      and expires after 48 h (fake clock)
- [x] A user who already has data or other members in their household cannot redeem
      (409) — one household per user in MVP
- [x] Members and invites are scoped to the caller's household (ADR-0004); the reusable
      404 helper arrives with the first endpoint that takes an object id (Task 12)

**Verification:**
- [x] `uv run pytest tests/integration/test_invites.py tests/integration/test_isolation.py`

**Dependencies:** Task 4
**Files likely touched:** `models/identity.py`, `repositories/invites.py`,
`services/households.py`, `api/routers/household.py`, `tests/integration/helpers.py`,
`docs/adr/0004-*.md`, migration
**Estimated scope:** M

### Task 8: Telegram linking and bot authentication (API side)

**Description:** `POST /me/telegram-link-code` returns a one-time 10-minute code;
bot-only endpoints protected by a service secret: `POST /bot/link` (code + Telegram id),
`POST /auth/telegram` (Telegram id → user access token), `POST /bot/register`
(Telegram-only account, see plan Open Question 1). ADR-0007.

**Acceptance criteria:**
- [x] Linking binds exactly one Telegram id to one user; reused or expired code → 400
- [x] Bot endpoints without a valid service secret → 401
- [x] A token issued via `/auth/telegram` has the same permissions as a normal user token

**Verification:**
- [x] `uv run pytest tests/integration/test_telegram_link.py`

**Dependencies:** Tasks 5, 7
**Files likely touched:** `models/identity.py`, `services/telegram_link.py`,
`api/routers/bot.py`, `api/deps.py`, migration, `docs/adr/0007-*.md`, tests
**Estimated scope:** M

### Checkpoint 1: identity
- [ ] Two users in one household and a third isolated user — covered by tests
- [ ] OpenAPI shows auth endpoints with examples
- [ ] Short report to the owner

---

## Phase 2: fx

### Task 9: Currency, Money and cross-rate domain

**Description:** `Currency` enum (RUB, BYN, USD), `Money` value object, cross-rate
derivation through BYN, single rounding step. Pure domain, no I/O.

**Acceptance criteria:**
- [x] RUB→USD and USD→RUB derived from BYN quotes with correct precision
- [x] Rounding happens once with `ROUND_HALF_UP`; `float` input is rejected

**Verification:**
- [x] `uv run pytest tests/unit/test_money.py tests/unit/test_cross_rates.py`

**Dependencies:** Task 1
**Files likely touched:** `domain/currency.py`, `domain/money.py`, `domain/fx.py`, tests
**Estimated scope:** S

### Task 10: NBRB client with recorded responses

**Description:** httpx client for NBRB rates (current and on date), normalising the
`Cur_Scale` (e.g. 100 RUB). Tests use recorded JSON responses through
`httpx.MockTransport`; network errors raise a typed `RateSourceUnavailable`.

**Acceptance criteria:**
- [x] Parses USD and RUB rates for a given date into BYN-per-unit `Decimal`
- [x] Timeouts and 5xx raise `RateSourceUnavailable`

**Verification:**
- [x] `uv run pytest tests/integration/test_nbrb_client.py`

**Dependencies:** Task 9
**Files likely touched:** `integrations/nbrb.py`, `tests/fixtures/nbrb/*.json`, tests
**Estimated scope:** S

### Task 11: Rate storage, rate service and `GET /fx/rates`

**Description:** `fx_rates` table (currency, date, BYN per unit) and migration;
`RateService.get_rate(from, to, date)` uses stored rates, fetches missing historical
rates on demand, falls back to the nearest earlier date and to the last known rate with a
warning log when NBRB is down; `GET /fx/rates?date=` and `GET /fx/convert`. ADR-0008.

**Acceptance criteria:**
- [ ] A weekend date uses the nearest earlier stored rate
- [ ] NBRB unavailable → last known rate is returned and a warning is logged
- [ ] Fetched historical rates are stored once and reused (no second HTTP call)

**Verification:**
- [ ] `uv run pytest tests/unit/test_rate_service.py tests/integration/test_fx_api.py`

**Dependencies:** Tasks 2, 10
**Files likely touched:** `models/fx.py`, `repositories/fx_rates.py`, `services/fx.py`,
`api/routers/fx.py`, migration, `docs/adr/0008-*.md`, tests
**Estimated scope:** M

### Checkpoint 2: fx
- [ ] Conversion on any historical date works, including weekends and NBRB outage

---

## Phase 3: ledger

### Task 12: Accounts with personal/shared permissions

**Description:** Add `assert_hidden_from` to `tests/integration/helpers.py` (ADR-0004) and
extend the invite "empty household" check: a user whose household already has accounts
cannot move. `Account` model (owner user nullable for shared, type
`card|cash|savings`, currency, archived flag) and CRUD endpoints. Personal accounts are
visible to the household and editable by the creator and the owner; shared accounts by
the owner.

**Acceptance criteria:**
- [ ] Member cannot edit another member's personal account (403); foreign household → 404
- [ ] Account currency cannot change after operations exist (409)

**Verification:**
- [ ] `uv run pytest tests/unit/test_permissions.py tests/integration/test_accounts.py`

**Dependencies:** Task 7
**Files likely touched:** `models/ledger.py`, `domain/permissions.py`,
`repositories/accounts.py`, `services/accounts.py`, `api/routers/accounts.py`, migration, tests
**Estimated scope:** M

### Task 13: Categories with a default set per household

**Description:** `Category` model (income/expense, name, household); default set created
in the same transaction as the household (registration and Telegram registration);
`GET/POST /categories`, rename/archive.

**Acceptance criteria:**
- [ ] A new household has the default income and expense categories
- [ ] Category names are unique per household and kind (case-insensitive)

**Verification:**
- [ ] `uv run pytest tests/integration/test_categories.py`

**Dependencies:** Task 7
**Files likely touched:** `models/ledger.py`, `repositories/categories.py`,
`services/categories.py`, `services/households.py`, `api/routers/categories.py`, migration
**Estimated scope:** S

### Task 14: Income and expense operations

**Description:** `Operation` model (type, amount `NUMERIC(14,2)`, currency, date,
category, account, comment, author, timestamps) and endpoints to create, read, edit and
delete. Original amount and currency are kept; category kind must match the type.

**Acceptance criteria:**
- [ ] Only the author or the owner can edit or delete (403 otherwise); foreign → 404
- [ ] Amount must be positive with at most 2 decimals; currency may differ from the account's
- [ ] Operation date is a calendar date in the household time zone

**Verification:**
- [ ] `uv run pytest tests/integration/test_operations.py`

**Dependencies:** Tasks 11, 12, 13
**Files likely touched:** `models/ledger.py`, `repositories/operations.py`,
`services/operations.py`, `api/routers/operations.py`, `api/schemas/operations.py`, migration
**Estimated scope:** M

### Task 15: Transfers between accounts with currency conversion

**Description:** `transfer` operation with source and target accounts; when currencies
differ, the target amount is converted at the rate on the operation date (or entered
explicitly); both amounts are stored.

**Acceptance criteria:**
- [ ] BYN → RUB transfer stores both amounts; balances of both accounts change
- [ ] Transfer to the same account or to a foreign household's account is rejected (422 / 404)

**Verification:**
- [ ] `uv run pytest tests/integration/test_transfers.py`

**Dependencies:** Task 14
**Files likely touched:** `models/ledger.py`, `services/operations.py`,
`api/schemas/operations.py`, migration, tests
**Estimated scope:** M

### Task 16: Account balances, operation filters and pagination

**Description:** Balance per account computed by an aggregate query from operations;
`GET /operations` with cursor or limit/offset pagination and filters: period, category,
account, member, currency.

**Acceptance criteria:**
- [ ] Balance equals the sum of incomes − expenses ± transfers in the account currency
- [ ] Each filter and their combination return correct results; page size is capped

**Verification:**
- [ ] `uv run pytest tests/integration/test_balances.py tests/integration/test_operation_filters.py`

**Dependencies:** Task 15
**Files likely touched:** `repositories/operations.py`, `repositories/accounts.py`,
`services/accounts.py`, `api/routers/operations.py`, tests
**Estimated scope:** M

### Checkpoint 3: ledger
- [ ] Two members record operations in BYN and RUB; balances and filters are correct
- [ ] Short report to the owner

---

## Phase 4: budgets

### Task 17: Budget approval window domain logic

**Description:** Pure function: given "now" in the household time zone and window bounds
(default day 20 to day 30, clamped to the last day of the month), return whether the
window for the next month is open and its bounds. Plus the permission rules for changing
a budget.

**Acceptance criteria:**
- [ ] Correct for 28, 29, 30 and 31-day months and for UTC/Minsk midnight edges
- [ ] Permission matrix (member/owner × in/outside window × draft/approved) is tested

**Verification:**
- [ ] `uv run pytest tests/unit/test_budget_window.py`

**Dependencies:** Task 1
**Files likely touched:** `domain/budget_window.py`, `domain/permissions.py`, tests
**Estimated scope:** S

### Task 18: Budget drafts, limits and owner approval API

**Description:** `Budget` (household, month, status `draft|approved`) and `BudgetLimit`
(category, amount in base currency) models; endpoints to view a month's budget,
set/change limits and approve (owner only), enforcing the window rules via the clock.

**Acceptance criteria:**
- [ ] Inside the window any member edits the draft; only the owner approves
- [ ] Outside the window and during the approved month only the owner can change it
- [ ] Limits only for expense categories of the same household

**Verification:**
- [ ] `uv run pytest tests/integration/test_budgets.py`

**Dependencies:** Tasks 13, 17
**Files likely touched:** `models/budgets.py`, `repositories/budgets.py`,
`services/budgets.py`, `api/routers/budgets.py`, migration, tests
**Estimated scope:** M

### Task 19: Budget execution, thresholds and notification outbox

**Description:** `GET /budgets/{month}/execution`: spent and remaining per category in base
currency (converted at operation date rates). After an expense is created or changed,
detect crossing 80% / 100% and write a notification to the `notifications` outbox with a
unique key (ADR-0009).

**Acceptance criteria:**
- [ ] Spent amounts in mixed currencies are converted at the rate on each operation's date
- [ ] Each threshold produces exactly one notification per category per month
- [ ] Notification is written in the same transaction as the operation

**Verification:**
- [ ] `uv run pytest tests/unit/test_thresholds.py tests/integration/test_budget_execution.py`

**Dependencies:** Tasks 16, 18
**Files likely touched:** `models/notifications.py`, `services/budget_execution.py`,
`services/operations.py`, `api/routers/budgets.py`, migration, `docs/adr/0009-*.md`
**Estimated scope:** M

### Checkpoint 4: budgets
- [ ] Window, owner-only approval and thresholds pass fake-clock tests
- [ ] Short report to the owner

---

## Phase 5: reports

### Task 20: Base, display and input currency settings

**Description:** Household base currency (RUB default, owner can change) and household
time zone; per-member display currency and default input currency (plan Open Question 2);
`GET/PATCH /household/settings` and `GET/PATCH /me/settings`.

**Acceptance criteria:**
- [ ] Only the owner changes household settings; members change only their own
- [ ] Balances endpoint returns totals in the member's display currency

**Verification:**
- [ ] `uv run pytest tests/integration/test_settings.py`

**Dependencies:** Task 16
**Files likely touched:** `models/identity.py`, `services/settings.py`,
`api/routers/settings.py`, migration, tests
**Estimated scope:** S

### Task 21: Period report

**Description:** `GET /reports?from=&to=`: totals, breakdown by category, by member and
by month, plan vs actual for each budget month in the period; amounts converted to the
requester's display currency at operation date rates.

**Acceptance criteria:**
- [ ] Two members get the same report in different display currencies; values differ only
      by conversion
- [ ] Plan vs actual uses budget limits converted from the base currency

**Verification:**
- [ ] `uv run pytest tests/integration/test_reports.py`

**Dependencies:** Tasks 19, 20
**Files likely touched:** `repositories/reports.py`, `services/reports.py`,
`api/routers/reports.py`, `api/schemas/reports.py`, tests
**Estimated scope:** M

### Task 22: CSV export of a report

**Description:** `GET /reports/export.csv` with the same parameters as the report;
UTF-8 with BOM for Excel, `Decimal` written without float artefacts.

**Acceptance criteria:**
- [ ] Exported CSV matches the JSON report for the same period
- [ ] Content-Type and file name headers are correct

**Verification:**
- [ ] `uv run pytest tests/integration/test_report_export.py`

**Dependencies:** Task 21
**Files likely touched:** `services/csv_export.py`, `api/routers/reports.py`, tests
**Estimated scope:** S

### Task 23: CSV import of operations with per-row errors

**Description:** `POST /operations/import` accepts a CSV in the documented format;
validates every row; either imports all valid rows or none (`dry_run` and strict modes)
and returns errors with row numbers. Size and row limits.

**Acceptance criteria:**
- [ ] Invalid rows are reported with row number, column and reason
- [ ] Unknown category or account in a row is an error, not an auto-create
- [ ] Format documented in README (Task 33)

**Verification:**
- [ ] `uv run pytest tests/unit/test_csv_import.py tests/integration/test_operations_import.py`

**Dependencies:** Task 16
**Files likely touched:** `services/csv_import.py`, `api/routers/operations.py`,
`tests/fixtures/csv/*`, tests
**Estimated scope:** M

### Checkpoint 5: reports
- [ ] Same report in two display currencies is consistent; coverage ≥ 85%
- [ ] Short report to the owner

---

## Phase 6: worker

### Task 24: arq worker setup and daily rate refresh job

**Description:** `worker/settings.py` with `WorkerSettings`, shared startup (DB, Redis,
logging); cron job refreshing the current NBRB rates once a day.

**Acceptance criteria:**
- [ ] Job stores today's rates; on NBRB failure logs a warning and does not crash
- [ ] Job is idempotent when run twice a day

**Verification:**
- [ ] `uv run pytest tests/worker/test_rate_refresh.py`
- [ ] Manual: `uv run arq family_pnl.worker.settings.WorkerSettings` starts against local Redis

**Dependencies:** Task 11
**Files likely touched:** `worker/settings.py`, `worker/jobs/fx.py`, tests
**Estimated scope:** S

### Task 25: Telegram notification delivery job

**Description:** `TelegramSender` protocol with an httpx implementation over the Bot API
and a fake for tests; job reads pending notifications from the outbox, sends them to
linked users and marks them sent; retries with backoff on failure.

**Acceptance criteria:**
- [ ] Sent notifications are not sent again after a worker restart
- [ ] Users without a linked Telegram are skipped with a log entry

**Verification:**
- [ ] `uv run pytest tests/worker/test_notification_delivery.py`

**Dependencies:** Tasks 19, 24
**Files likely touched:** `integrations/telegram.py`, `worker/jobs/notifications.py`,
`repositories/notifications.py`, tests
**Estimated scope:** M

### Task 26: Daily budget approval reminder job

**Description:** Daily job (per household time zone): while next month's budget is not
approved inside the window, remind the owner; after the window ends, mark the budget as
not approved and keep reminding.

**Acceptance criteria:**
- [ ] With a fake clock: no reminder before day 20, one reminder per day from day 20,
      none after approval
- [ ] After the window ends the budget is marked not approved and reminders continue

**Verification:**
- [ ] `uv run pytest tests/worker/test_budget_reminders.py`

**Dependencies:** Task 25
**Files likely touched:** `worker/jobs/budgets.py`, `services/budgets.py`, migration (flag), tests
**Estimated scope:** S

### Checkpoint 6: worker
- [ ] Jobs pass with a fake clock and a fake sender; worker starts locally
- [ ] Short report to the owner

---

## Phase 7: bot

### Task 27: Bot skeleton, API client and `/start`

**Description:** `family_pnl_bot` package: aiogram 3 dispatcher, config, typed httpx API
client with token caching via `/auth/telegram`; `/start` registers a Telegram-only account
or redeems an invite (`/start <code>`); `/link <code>` links an existing API account.
`/link` attempts are throttled per Telegram user (ADR-0007: the bot is the only way to try
link codes).
The bot imports nothing from `family_pnl`.

**Acceptance criteria:**
- [ ] New Telegram user gets an account and household via `/start`
- [ ] `/start <invite>` joins the household; errors from the API are shown in Russian
- [ ] Import-linter or a test fails if `family_pnl_bot` imports `family_pnl`

**Verification:**
- [ ] `uv run pytest tests/bot/test_start.py`
- [ ] Manual: test bot token in `.env`, `uv run python -m family_pnl_bot`, send `/start`

**Dependencies:** Task 8
**Files likely touched:** `family_pnl_bot/__main__.py`, `config.py`, `api_client.py`,
`handlers/start.py`, tests
**Estimated scope:** M

### Task 28: Quick entry message parser

**Description:** Pure parser: `кофе 5.50`, `такси 300 rub`, `+зарплата 2500 byn`,
commas as decimal separators, currency aliases (`р`, `руб`, `$`, `бел`).
Returns type, amount `Decimal`, optional currency and the category text.

**Acceptance criteria:**
- [ ] Table-driven tests cover the spec examples, aliases, commas and invalid input
- [ ] Never produces `float`

**Verification:**
- [ ] `uv run pytest tests/bot/test_parser.py`

**Dependencies:** Task 27 (package only)
**Files likely touched:** `family_pnl_bot/parser.py`, tests
**Estimated scope:** S

### Task 29: Quick entry handler

**Description:** Message handler: parse, default the currency to the member's input
currency, match the category by name (case-insensitive, prefix), otherwise show inline
buttons; account chosen by default rule or buttons; create the operation through the API;
confirm with an "undo" button.

**Acceptance criteria:**
- [ ] Exact category match creates the operation in one message
- [ ] No match → buttons; selection creates the operation
- [ ] Undo deletes the operation via the API

**Verification:**
- [ ] `uv run pytest tests/bot/test_quick_entry.py` (mocked API client)

**Dependencies:** Tasks 20, 28
**Files likely touched:** `handlers/quick_entry.py`, `keyboards.py`, `api_client.py`, tests
**Estimated scope:** M

### Task 30: Balance, monthly report and display currency in the bot

**Description:** `/balance`, `/report` (current month, previous month via buttons),
`/currency` to switch the display currency.

**Acceptance criteria:**
- [ ] Output in the member's display currency, amounts formatted with 2 decimals
- [ ] Switching currency updates `/me/settings` and the next report

**Verification:**
- [ ] `uv run pytest tests/bot/test_reports_handlers.py`

**Dependencies:** Tasks 21, 27
**Files likely touched:** `handlers/reports.py`, `formatting.py`, `keyboards.py`, tests
**Estimated scope:** M

### Task 31: Budget draft, limits and approval in the bot

**Description:** `/budget`: view next month's draft and execution of the current month;
set a limit (`/limit продукты 800`); owner sees an "Approve" button. API errors about the
window or role are explained in Russian.

**Acceptance criteria:**
- [ ] Member sets a limit inside the window; outside it gets a clear message
- [ ] Only the owner sees and can use "Approve"

**Verification:**
- [ ] `uv run pytest tests/bot/test_budget_handlers.py`

**Dependencies:** Tasks 18, 27
**Files likely touched:** `handlers/budget.py`, `keyboards.py`, `api_client.py`, tests
**Estimated scope:** M

### Checkpoint 7: bot
- [ ] Owner checks the bot on a real test token: two accounts, one household, operations in
      BYN and RUB, report in different display currencies

---

## Phase 8: MVP packaging

### Task 32: Dockerfiles and full Docker Compose stack

**Description:** Multi-stage Dockerfile (uv build stage, slim non-root runtime) for API,
worker and bot; `docker-compose.yml` with API, bot, worker, PostgreSQL, Redis, a migrate
step, healthchecks and `restart: unless-stopped`; Docker build in CI.
Run the API with `uvicorn --factory family_pnl.api.main:create_app` (done in Task 2).

**Acceptance criteria:**
- [ ] `docker compose up --build` starts all services; `/health` and `/docs` answer
- [ ] Containers run as non-root; only the API port is published
- [ ] CI builds the image

**Verification:**
- [ ] Manual: `docker compose up --build`, then `/health`, bot `/start`
- [ ] CI green with the Docker build job

**Dependencies:** Task 31
**Files likely touched:** `Dockerfile`, `docker-compose.yml`, `.dockerignore`,
`.github/workflows/ci.yml`
**Estimated scope:** M

### Task 33: README.md, README.ru.md and architecture diagram

**Description:** Project description, architecture diagram (Mermaid), setup on Windows and
Linux, configuration (`.env.example`), CSV format, bot commands, known limitations, links
to ADRs. Russian version mirrors the English one.

**Acceptance criteria:**
- [ ] A new developer can run the stack from README alone
- [ ] No "pet project", "educational", invented users or metrics

**Verification:**
- [ ] Manual: follow README from a clean clone

**Dependencies:** Task 32
**Files likely touched:** `README.md`, `README.ru.md`, `docs/architecture.md`
**Estimated scope:** S

### Task 34: Final reviews and fixes

**Description:** Run `/skillfactory-mentor:sf-review` and the github-portfolio-builder
review, then `/engineering:code-review` on the whole codebase; fix findings in small PRs.

**Acceptance criteria:**
- [ ] Every finding is fixed or answered with a reason
- [ ] CI green after fixes

**Verification:**
- [ ] Review reports saved to `.reports/` (not committed)

**Dependencies:** Task 33
**Estimated scope:** M (several small PRs)

### Checkpoint 8: MVP complete
- [ ] All spec success criteria except deployment are met
- [ ] Owner review and go-ahead for Phase 9

---

## Phase 9: deploy (after MVP, needs owner input)

### Task 35: VPS provisioning and `docs/deploy.md`

**Description:** Owner chooses a VPS (spec Q3). Run uvicorn with `--proxy-headers` and a
trusted `--forwarded-allow-ips` so the login rate limit sees real client IPs (ADR-0006). Server hardening (SSH keys, firewall with
only required ports), Docker install, `.env` on the server, HTTPS via a reverse proxy if
the API is public. Every step documented in `docs/deploy.md`.

**Acceptance criteria:**
- [ ] Stack runs on the VPS and restarts after a reboot
- [ ] Only SSH and (optionally) HTTPS are open

**Verification:**
- [ ] Manual: reboot the server, check `/health` and the bot

**Dependencies:** Checkpoint 8, owner provides access
**Estimated scope:** M

### Task 36: CD workflow with migrations

**Description:** GitHub Actions deploy on push to `main` (after CI): build and push the
image to GHCR, SSH to the VPS, pull, run migrations, restart services.

**Acceptance criteria:**
- [ ] A merge into `main` deploys automatically; a failed migration stops the deploy

**Verification:**
- [ ] Manual: merge a trivial change and see the new version on `/health`

**Dependencies:** Task 35, GitHub Secrets added by the owner
**Estimated scope:** S

### Task 37: Daily PostgreSQL backups with rotation and restore procedure

**Description:** `scripts/backup.sh` with `pg_dump`, daily cron or a compose service,
rotation (e.g. 7 daily + 4 weekly), documented and tested restore.

**Acceptance criteria:**
- [ ] Backups appear daily and old ones are rotated
- [ ] Restore into a scratch database succeeds following `docs/deploy.md`

**Verification:**
- [ ] Manual: restore the latest backup into a test database

**Dependencies:** Task 35
**Estimated scope:** S

### Checkpoint 9: Production
- [ ] Service survives a reboot; a backup has been restored once; owner sign-off
