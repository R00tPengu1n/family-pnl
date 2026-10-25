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
    "archived": "Этот счёт или категория в архиве.",
    "rates_unavailable": "Курсы валют сейчас недоступны. Попробуйте чуть позже.",
    "credentials_already_set": "У вас уже есть email и пароль: входите через POST /auth/login.",
}
UNKNOWN_ERROR = "Что-то пошло не так. Попробуйте ещё раз."

HELP = (
    "Записывайте траты и доходы одним сообщением: «кофе 5.50», «+зарплата 2500 byn».\n"
    "Сначала откройте счёт: /account Карта BYN. Ещё: /balance, /report, /budget, /limit, "
    "/currency, /input, /password."
)

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


CHOOSE_CATEGORY = "Какая категория?"
CHOOSE_ACCOUNT = "С какого счёта?"
NO_ACCOUNTS = "Сначала заведите счёт: /account Карта BYN"
ENTRY_EXPIRED = "Эта запись устарела. Отправьте сообщение ещё раз."
ENTRY_UNDONE = "Запись отменена."
ENTRY_ALREADY_GONE = "Этой записи уже нет."
UNDO_BUTTON = "Отменить"


def recorded(*, income: bool, amount: str, category: str, account: str) -> str:
    kind = "Доход" if income else "Расход"
    return f"{kind} {amount} записан: «{category}», счёт «{account}»."


NO_ACCOUNTS_YET = "Счетов пока нет. Заведите первый: /account Карта BYN"


def display_currency(code: str) -> str:
    return f"Суммы показываются в {code}. Выберите другую валюту:"


def currency_changed(code: str) -> str:
    return f"Готово: отчёты и балансы теперь в {code}."


APPROVE_BUTTON = "Утвердить"
LIMIT_USAGE = "Напишите категорию и сумму: /limit продукты 800"
LIMIT_REFUSED = (
    "Сейчас менять бюджет может только владелец: окно утверждения закрыто или бюджет уже утверждён."
)
APPROVE_REFUSED = "Утвердить бюджет может только владелец семьи."
NOTHING_TO_APPROVE = "Бюджета на этот месяц ещё нет: сначала задайте лимиты через /limit."


def no_expense_category(typed: str) -> str:
    return f"Не нашёл категорию расходов «{typed}»."


def limit_set(category: str, month: str, value: str) -> str:
    return f"Лимит «{category}» на {month.lower()}: {value}."


def approved(month: str) -> str:
    return f"Бюджет на {month.lower()} утверждён."


def input_currency(code: str) -> str:
    return f"Сумма без валюты записывается в {code}. Выберите другую валюту:"


def input_currency_changed(code: str) -> str:
    return f"Готово: сумма без валюты теперь в {code}."


ACCOUNT_USAGE = (
    "Напишите название и валюту: /account Карта BYN (добавьте «общий» для общего счёта)."
)


def account_created(name: str, currency: str, shared: bool) -> str:
    kind = "Общий счёт" if shared else "Счёт"
    return f"{kind} «{name}» в {currency} создан."


SHARED_ACCOUNT_REFUSED = "Общий счёт может открыть только владелец семьи."


def credentials_code(code: str) -> str:
    return (
        f"Код для email и пароля: {code}, действует 10 минут.\n"
        "Отправьте его в API: POST /auth/credentials с полями code, email и password. "
        "Пароль в этот чат не пишите."
    )
