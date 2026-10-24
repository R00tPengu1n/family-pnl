# ADR-0007: Bot authentication

- Status: accepted
- Date: 2026-10-24

## Context

The Telegram bot is the main client and talks only to the REST API (spec). It acts for many
users, cannot store their passwords, and must not get more power than the user it acts for.
People also need a way in without a web frontend (spec question 1, resolved: passwordless
registration from the bot) and a way to connect an existing API account to Telegram.

## Decision

- **Service secret.** The bot sends `X-Bot-Token` with a shared secret
  (`FAMILY_PNL_BOT_API_SECRET`, at least 32 characters), compared with `hmac.compare_digest`.
  Without a configured secret every bot endpoint answers 401: the bot API is off by default.
- **The secret only identifies the bot; it carries no user permissions.** The bot exchanges a
  linked Telegram user id for that user's normal 15-minute access token
  (`POST /auth/telegram`) and calls every other endpoint with it. Household scoping and role
  checks therefore apply to bot requests exactly as to any other client.
- **Registration from the bot** (`POST /bot/register`) creates a user with a Telegram id and no
  email or password — as the owner of a new household, or as a member through an invite code,
  validated before anything is written. A CHECK constraint keeps at least one login method
  (email or Telegram) on every user; email and password exist together or not at all.
- **Linking an existing account**: the signed-in user requests a code
  (`POST /me/telegram-link-code`, 8 characters without look-alikes, 10 minutes, single use,
  stored as a digest) and sends it to the bot, which calls `POST /bot/link`. One Telegram id
  belongs to one user; a user has at most one linked Telegram id.
- Telegram ids are stored as `BIGINT` (they exceed 32 bits) with a unique constraint; a lost
  race for one id becomes 409 `telegram_taken`, any other integrity error is re-raised.

## Consequences

- Whoever holds the bot secret can act as any Telegram-linked user. The secret lives only in
  `.env` / GitHub Secrets, is never logged (`SecretStr`), and must be rotated if leaked.
- No refresh tokens for the bot: it re-exchanges the Telegram id when a token expires.
- Telegram-only users cannot use email login until a later feature adds email and password.
