# ADR-0002: Layering and dependency direction

- Status: accepted
- Date: 2026-10-24

## Context

Business rules (money and rounding, cross rates, the budget approval window, permission
rules) are the part of the system most worth testing exhaustively and least worth
coupling to frameworks. The Telegram bot must stay a pure API client. An agent writes
most of the code, so the structure has to be checked mechanically, not by convention.

## Decision

The package `family_pnl` is split into layers with one dependency direction:

```
api ──► services ──► repositories ──► models
            │
            └──────► domain ──► core
```

- `domain` is pure Python: no FastAPI, SQLAlchemy, httpx, Redis or arq, and nothing from
  `family_pnl` except `core`. It is the main target of fast unit tests.
- `services` orchestrate repositories and domain rules; they raise `DomainError`
  subclasses, which `api` maps to HTTP responses in one JSON format.
- `api` and `worker` are independent entry points over the same services.
- `family_pnl_bot` imports nothing from `family_pnl` and talks only to the REST API.

The rules are import-linter contracts in `pyproject.toml`, run by `scripts/check.ps1` in
the fast stage and in CI.

## Consequences

- A forbidden import fails the edit-loop check within seconds, before review.
- Domain logic is tested without a database; integration tests cover the layers above.
- Some code that would be shorter with a direct framework call goes through a service or
  repository instead; this is the intended cost.
