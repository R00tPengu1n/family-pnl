"""Notification texts and the delivery retry schedule (ADR-0009)."""

from datetime import timedelta

MAX_DELIVERY_ATTEMPTS = 10
MAX_RETRY_DELAY = timedelta(hours=6)


def retry_delay(failed_attempts: int) -> timedelta:
    """1, 2, 4, 8... minutes after the 1st, 2nd, 3rd, 4th failure; at most six hours."""
    return min(timedelta(minutes=2 ** (failed_attempts - 1)), MAX_RETRY_DELAY)


def gives_up(failed_attempts: int) -> bool:
    return failed_attempts >= MAX_DELIVERY_ATTEMPTS


def threshold_message(
    *, month: str, category: str, threshold: int, spent: str, limit: str, currency: str
) -> str:
    """The text members get when a category reaches 80% or 100% of its monthly limit."""
    if threshold >= 100:
        return (
            f"Бюджет {month}, «{category}»: лимит исчерпан — "
            f"потрачено {spent} из {limit} {currency}."
        )
    return (
        f"Бюджет {month}, «{category}»: потрачено {spent} из {limit} {currency} — "
        f"{threshold}% лимита."
    )


def reminder_message(*, month: str, window_closes: str, missed: bool) -> str:
    """The daily text the owner gets while a budget is not approved."""
    if missed:
        return f"Бюджет на {month} не утверждён: окно утверждения закрылось {window_closes}."
    return f"Бюджет на {month} ещё не утверждён. Окно утверждения открыто до {window_closes}."
