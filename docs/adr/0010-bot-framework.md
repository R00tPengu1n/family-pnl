# ADR-0010: aiogram 3 for the bot, and pydantic 2.13

- Status: accepted
- Date: 2026-10-25

## Context

The Telegram bot (`family_pnl_bot`) needs long polling, command and message routing,
inline keyboards and callback queries. It is a client of the REST API only (ADR-0007) and
lives in the same repository and lock file as the API.

The spec names aiogram 3. Every aiogram 3 release pins `pydantic<2.14` (3.28–3.31), while
the project had `pydantic>=2.14.1` from its first commit; no code relies on 2.14.

Options considered:

- **aiogram 3, pydantic lowered to 2.13.5** — the framework the spec names; one shared
  environment.
- **Raw Bot API over httpx** — no new dependency (the worker already sends messages this
  way), but routing, filters, keyboards and update parsing would be written by hand.
- **A separate environment for the bot** — a uv workspace still resolves one lock file, so
  it would need a second project and a second CI path.

## Decision

Use aiogram 3 (3.31.0) and require `pydantic>=2.13.5`. aiogram's own upper bound decides
when pydantic can move again.

## Consequences

- The whole test suite passes on pydantic 2.13.5; the API behaves the same.
- pydantic upgrades wait for aiogram; `pip-audit` in CI still flags vulnerable versions.
- aiogram brings aiohttp (its HTTP session for the Bot API); the API and the worker keep
  using httpx.
