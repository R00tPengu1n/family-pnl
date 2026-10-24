# ADR-0004: Household isolation returns 404

- Status: accepted
- Date: 2026-10-24

## Context

Several unrelated families use one deployment. A request for another household's account,
operation, budget or member must never succeed, and it must not even confirm that the object
exists: a 403 for "exists but not yours" against a 404 for "does not exist" lets an attacker
enumerate ids. The spec requires 404 and a test for every endpoint.

## Decision

- **Scope at the query, not after it.** Repository methods that read household data take the
  household id from the authenticated user and put it in the `WHERE` clause. A foreign object
  is then simply not found, and the service raises `NotFoundError` exactly as for a missing id.
- **The household comes from the database, not from the request or the token.** The current
  user's membership is loaded on every request (`AuthService.current_user`); clients never
  send a household id for their own data.
- **Roles are checked after scoping.** Inside the own household a forbidden action is a 403
  (`permission_denied`); outside it, the object does not exist (404).
- **Cross-household lookups are explicit exceptions.** Redeeming an invite looks a code up
  across households by design; the code is 128 random bits stored as a digest, and every
  failure gives one `invite_invalid` answer.
- **Tests.** Every endpoint that takes an object id gets a test where a user of another
  household receives the same 404 body as for a random id; a shared helper does this from
  Task 12 on, when the first such endpoint (accounts) appears.

## Consequences

- Forgetting the household filter in a repository is the main risk; the per-endpoint test
  makes that visible.
- Error bodies cannot distinguish "missing" from "foreign", which also makes debugging a
  wrong id slightly harder for legitimate clients.
