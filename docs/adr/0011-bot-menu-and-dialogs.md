# ADR-0011: Reply-keyboard menu and dialogs in the bot

- Status: accepted
- Date: 2026-11-01

## Context

The first manual run showed that commands with arguments (`/account Карта BYN`,
`/limit продукты 800`) are hard to discover: the owner could not open an account without
reading the code. Family members are not expected to learn commands. The owner asked for
Russian buttons for every action and a menu that is always there while the bot waits,
and that gives way while the bot asks a question.

## Decision

- **A reply keyboard is the menu.** It sits under the input field (`is_persistent`), so
  it is there whenever the bot waits. Every plain reply carries it; replies with inline
  buttons (a report with month arrows, a quick entry to undo) keep the keyboard the chat
  already shows.
- **Multi-step actions are aiogram FSM dialogs.** Each question replaces the menu with
  the possible answers plus "Отмена"; the result brings the menu back. A menu button
  always wins over a dialog: it ends the dialog and does its own action.
- **Dialog state lives in memory** (aiogram's `MemoryStorage`). A restart forgets a
  half-finished dialog; the member presses the button again. Redis storage would survive
  restarts but would give the bot a connection it does not need today (the bot talks
  only to the API).
- **The logic stays outside aiogram.** Dialog handlers only keep the state; replies come
  from the same aiogram-free functions the commands use, so both paths share behaviour
  and tests.
- **Invites become links.** The owner gets `t.me/<bot>?start=<code>` to forward; the
  invited person opens it and `/start <code>` registers them into the family.
- **The bot still never asks for a password** (ADR-0007). The email-and-password screen
  explains why the bot does not need one and how to set it in the API with a one-time
  code.

## Consequences

- Commands stay as shortcuts and keep working.
- A restart of the bot loses dialogs in progress; nothing is written before the last
  answer, so no half-created data is left behind.
- Scaling the bot to several processes would need shared FSM storage (Redis).
