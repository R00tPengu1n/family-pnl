"""Texts the bot sends, and API errors explained in Russian."""

from family_pnl_bot.api_client import ApiError

ERRORS = {
    "invite_invalid": (
        "Код приглашения не подходит или устарел. Попросите владельца прислать новый."
    ),
    "already_member": "Вы уже состоите в этой семье.",
    "household_not_empty": "В вашей семье уже есть данные, поэтому перейти в другую нельзя.",
    "telegram_taken": "Этот Telegram уже зарегистрирован. Наберите /start, чтобы продолжить.",
    "telegram_already_linked": "К этому аккаунту уже привязан другой Telegram.",
    "telegram_not_registered": "Вы ещё не зарегистрированы. Наберите /start.",
    "link_code_invalid": "Код не подходит или устарел. Запросите новый в приложении.",
    "api_unavailable": "Сервис сейчас недоступен. Попробуйте чуть позже.",
}
UNKNOWN_ERROR = "Что-то пошло не так. Попробуйте ещё раз."

HELP = "Записывайте траты и доходы одним сообщением: «кофе 5.50», «+зарплата 2500 byn»."

LINK_USAGE = "Отправьте код из приложения: /link K7Q2-M9XD"
LINK_THROTTLED = "Слишком много попыток. Попробуйте через 15 минут."


def error_text(error: ApiError) -> str:
    return ERRORS.get(error.code, UNKNOWN_ERROR)


def created(household: str) -> str:
    return f"Готово! Создана семья «{household}», вы — её владелец.\n{HELP}"


def joined(household: str) -> str:
    return f"Вы присоединились к семье «{household}».\n{HELP}"


def welcome_back(household: str) -> str:
    return f"С возвращением! Ваша семья — «{household}».\n{HELP}"


def linked(account: str) -> str:
    return f"Telegram привязан к аккаунту {account}."
