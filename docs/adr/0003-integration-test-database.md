# ADR-0003: Integration test database

- Status: accepted
- Date: 2026-10-24

## Context

The spec requires every endpoint to be tested through HTTP against a real PostgreSQL with
migrations applied, including household isolation. SQLite or mocks would hide differences
that matter here: `NUMERIC` precision, `timestamptz`, constraint behaviour, locking. Tests
must also stay fast enough for the 90-second task-end budget in `CONSTRAINTS.md` and must
never leak data between tests.

## Decision

- **Where the database comes from.** If `TEST_DATABASE_URL` is set, tests use it (CI runs
  a PostgreSQL 16 service). Otherwise a throwaway `postgres:16-alpine` container is started
  with testcontainers for the test session. A missing database is an error, never a skip.
- **Schema.** `alembic upgrade head` runs once per session through the same migrations as
  production; a separate test downgrades to base and upgrades back.
- **Isolation.** Each test gets a connection with an open outer transaction and a session
  bound with `join_transaction_mode="create_savepoint"`. Code under test can call
  `commit()`; it commits a savepoint. The outer transaction is rolled back after the test.
- **Wiring.** The API's `get_session` dependency is overridden with that session, so HTTP
  tests and direct assertions see the same data.
- **Event loop.** One asyncio loop per test session, shared by the engine and all tests.

- **Parallel workers** (pytest-xdist, added later): each worker gets its own database on the
  same server (`<name>_gwN`, created from the `postgres` maintenance database) and its own
  Redis database number, so workers never share state. Locally the tests reuse the dev
  servers from `docker-compose.dev.yml` with a separate `family_pnl_test` database
  (`TEST_DATABASE_URL` / `TEST_REDIS_URL`, read from the environment or `.env`).

## Consequences

- Tests exercise real SQL and real migrations; there is no second schema definition.
- Rollback is cheaper than truncating tables and keeps tests order-independent; a test
  proves it by inserting the same kind of row twice in separate tests.
- Code that opens its own connections bypasses the per-test transaction (for example the
  health check's ping); such code must not write data.
- Local runs need Docker Desktop; the first run pulls the PostgreSQL image.
- Tests must never point at the dev database itself: one test downgrades the schema to base.
