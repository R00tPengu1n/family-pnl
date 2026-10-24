# ADR-0005: Refresh token rotation with reuse detection

- Status: accepted
- Date: 2026-10-24

## Context

Access tokens live 15 minutes and are not stored; refresh tokens live 30 days and are the
long-lived credential. Clients are a Telegram bot and API users, so a refresh token can leak
through logs, backups or a compromised client. A leaked long-lived token must not give an
attacker a silent, permanent session.

## Decision

- Refresh tokens are 256-bit random strings; the database keeps only their SHA-256 digest.
- Every token belongs to a **family**: all tokens obtained from one login by rotation.
- `POST /auth/refresh` rotates: the presented token is revoked and a new pair is issued in the
  same family. Each refresh token therefore works exactly once.
- Presenting a token that was already rotated or revoked is treated as a replay of a stolen
  token: the whole family is revoked and a `refresh_token_reuse` warning is logged. The
  legitimate user signs in again; the attacker's copy is dead as well.
- The token row is read with `SELECT … FOR UPDATE`, so two concurrent refreshes of one token
  are serialised: the second sees the first's rotation and is handled as a replay.
- `POST /auth/logout` revokes the family of the presented token and always answers 204, so it
  does not reveal whether a token existed. Other logins (other families) are unaffected.

## Consequences

- A stolen refresh token is usable at most until the legitimate client refreshes next.
- A client that sends the same refresh twice in parallel (a retry without waiting) loses the
  session and must log in again. This is the price of strict detection and is acceptable for
  the bot, which refreshes from one place.
- Access tokens stay stateless: after logout or a revoked family an access token keeps
  working until it expires (at most 15 minutes).
- Revoked and expired rows accumulate; a periodic cleanup job belongs to the worker.
