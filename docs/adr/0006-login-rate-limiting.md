# ADR-0006: Login rate limiting in Redis, failing open

- Status: accepted
- Date: 2026-10-24

## Context

`POST /auth/login` verifies an argon2 hash, which is deliberately expensive. Without a limit
an attacker can guess passwords for one account, spray one password over many accounts, or
burn CPU. The spec sets the limit: 5 failed attempts per 15 minutes per email and per IP.
Redis is already part of the stack.

## Decision

- Two counters per failed login: one per email (stored as a SHA-256 digest, so Redis holds
  no plain emails) and one per client IP. `INCR` plus `EXPIRE … NX` in one transaction gives a
  fixed window that starts at the first failure.
- The check runs **before** the password is verified: a refused attempt costs no argon2 work,
  and the sixth attempt is refused even with the right password (otherwise the limit would
  still confirm a correct guess).
- A successful login resets the email counter, not the IP counter: an attacker who controls
  one account cannot use it to reset an IP that is spraying other accounts.
- `429 Too Many Requests` with `Retry-After` = remaining TTL of the blocking counter, in the
  common error format (`too_many_attempts`).
- **Fail open:** if Redis is unavailable, logins proceed and `rate_limit_unavailable` is
  logged. Failing closed would turn a cache outage into a full login outage.

## Consequences

- Anyone can lock an email out for up to 15 minutes with five wrong passwords. This is the
  usual trade-off of per-account limits and is bounded by the window.
- A fixed window allows a burst of up to 10 attempts around a window boundary; concurrent
  attempts can slightly exceed 5 because check and increment are separate round trips.
  Both are acceptable at this scale.
- During a Redis outage there is no limit; the warning makes the outage visible.
- Behind a reverse proxy the client IP must come from the proxy (`uvicorn --proxy-headers`
  with trusted `--forwarded-allow-ips`), otherwise every request shares the proxy's IP
  (deployment, Task 35).
