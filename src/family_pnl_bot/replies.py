"""Replies to /start, /link and invites, apart from aiogram so they are cheap to test."""

from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError
from family_pnl_bot.throttle import AttemptLimiter


async def start_reply(
    api: ApiClient, telegram_id: int, name: str | None, invite_code: str | None
) -> str:
    try:
        me = await api.me(telegram_id)
    except ApiError as error:
        if error.code != "telegram_not_registered":
            return messages.error_text(error)
    else:
        if invite_code is None:
            return messages.welcome_back(me.household_name)
        try:
            joined = await api.redeem_invite(telegram_id, invite_code)
        except ApiError as error:
            return messages.error_text(error)
        return messages.joined(joined.household_name)
    try:
        me = await api.register(telegram_id, display_name=name, invite_code=invite_code)
    except ApiError as error:
        return messages.error_text(error)
    if invite_code is None:
        return messages.created(me.household_name)
    return messages.joined(me.household_name)


async def link_reply(
    api: ApiClient, limiter: AttemptLimiter, telegram_id: int, code: str | None
) -> str:
    if not code:
        return messages.LINK_USAGE
    if not limiter.allow(telegram_id):
        return messages.LINK_THROTTLED
    try:
        me = await api.link(telegram_id, code)
    except ApiError as error:
        return messages.error_text(error)
    return messages.linked(me.email or me.display_name or me.household_name)


async def invite_replies(api: ApiClient, telegram_id: int, bot_username: str) -> list[str]:
    """The owner's invite: how to pass it on, then a message to forward with the link.

    The link opens the bot with `/start <code>`, which registers the person into the family.
    """
    try:
        body = await api.request(telegram_id, "POST", "/household/invites")
    except ApiError as error:
        if error.code == "permission_denied":
            return [messages.INVITE_REFUSED]
        return [messages.error_text(error)]
    link = f"https://t.me/{bot_username}?start={body['code']}"
    return [messages.INVITE_HOWTO, messages.invite(link)]
