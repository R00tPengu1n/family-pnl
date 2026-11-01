"""Texts the bot sends, and API errors explained in Russian."""

from family_pnl_bot import menu
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

ENTRY_EXAMPLES = "«кофе 5.50», «такси 300 rub», «+зарплата 2500 byn»"

HELP = (
    "Как пользоваться ботом:\n"
    f"• Траты и доходы — одним сообщением: {ENTRY_EXAMPLES}. "
    "Плюс в начале — доход. Без валюты сумма записывается в валюту ввода.\n"
    f"• {menu.TOP_UP} — записать поступление: выберите счёт и напишите сумму.\n"
    f"• {menu.BALANCE} — сколько денег на счетах и сколько осталось по лимитам.\n"
    f"• {menu.REPORT} — доходы и расходы за месяц.\n"
    f"• {menu.BUDGET} — лимиты на следующий месяц и траты в этом.\n"
    f"• {menu.NEW_ACCOUNT} — открыть карту, наличные или копилку.\n"
    f"• {menu.SETTINGS} — валюты, приглашение в семью, email и пароль.\n"
    f"Передумали посередине — нажмите «{menu.CANCEL}»."
)

RECORD_HINT = (
    f"Напишите одним сообщением, на что и сколько: {ENTRY_EXAMPLES}.\n"
    "Плюс в начале — доход. Категорию бот подберёт по названию или спросит.\n"
    f"Пополнить счёт удобнее кнопкой «{menu.TOP_UP}»."
)

FIRST_ACCOUNT_STEP = f"Откройте счёт: кнопка «{menu.NEW_ACCOUNT}»."
FIRST_ENTRY_STEP = f"Записывайте траты одним сообщением: {ENTRY_EXAMPLES}."

LINK_USAGE = "Отправьте код из приложения: /link K7Q2-M9XD"
LINK_THROTTLED = "Слишком много попыток. Попробуйте через 15 минут."


def error_text(error: ApiError) -> str:
    return ERRORS.get(error.code, UNKNOWN_ERROR)


def created(household: str) -> str:
    return (
        "Готово, вы зарегистрированы! Пароль не нужен: бот узнаёт вас по Telegram.\n"
        f"Создана семья «{household}», вы её владелец.\n\n"
        "С чего начать:\n"
        f"1. {FIRST_ACCOUNT_STEP}\n"
        f"2. {FIRST_ENTRY_STEP}\n"
        f"3. Позовите семью: «{menu.SETTINGS}» → «{menu.INVITE}».\n\n"
        "Всё остальное — в меню внизу."
    )


def joined(household: str) -> str:
    return (
        f"Готово, вы в семье «{household}»! Пароль не нужен: бот узнаёт вас по Telegram.\n\n"
        "С чего начать:\n"
        f"1. {FIRST_ACCOUNT_STEP}\n"
        f"2. {FIRST_ENTRY_STEP}\n\n"
        "Всё остальное — в меню внизу."
    )


def welcome_back(household: str) -> str:
    return f"С возвращением! Ваша семья — «{household}». Меню внизу."


def linked(account: str) -> str:
    return f"Telegram привязан к аккаунту {account}."


MENU_SHOWN = "Меню внизу."
CANCELLED = "Отменил. Меню внизу."
SETTINGS_TITLE = "Настройки:"

CHOOSE_CATEGORY = "Какая категория?"
CHOOSE_ACCOUNT = "С какого счёта?"
NO_ACCOUNTS = f"Сначала откройте счёт: кнопка «{menu.NEW_ACCOUNT}»."
ENTRY_EXPIRED = "Эта запись устарела. Отправьте сообщение ещё раз."
ENTRY_UNDONE = "Запись отменена."
ENTRY_ALREADY_GONE = "Этой записи уже нет."
UNDO_BUTTON = "Отменить"


def recorded(*, income: bool, amount: str, category: str, account: str) -> str:
    kind = "Доход" if income else "Расход"
    return f"{kind} {amount} записан: «{category}», счёт «{account}»."


ASK_TOP_UP_ACCOUNT = "Какой счёт пополнить?"
CHOOSE_ACCOUNT_BUTTON = "Выберите счёт кнопкой внизу."
TOP_UP_AMOUNT_INVALID = "Не понял сумму. Напишите, например, 2500 или «зарплата 2500»."


def ask_top_up_amount(account: str) -> str:
    return (
        f"Сколько пришло на «{account}»? Напишите сумму, например 2500, "
        "или откуда и сколько: «зарплата 2500»."
    )


NO_ACCOUNTS_YET = f"Счетов пока нет. Откройте первый: кнопка «{menu.NEW_ACCOUNT}»."


def display_currency(code: str) -> str:
    return f"Суммы показываются в {code}. Выберите другую валюту:"


def currency_changed(code: str) -> str:
    return f"Готово: отчёты и балансы теперь в {code}."


NO_LIMITS_THIS_MONTH = f"Лимитов на этот месяц нет: их задают в «{menu.BUDGET}»."

CHOOSE_CURRENCY_BUTTON = "Выберите валюту кнопкой внизу."

APPROVE_BUTTON = "Утвердить"
LIMIT_BUTTON = "✏️ Задать лимит"
LIMIT_USAGE = "Напишите категорию и сумму: /limit продукты 800"
LIMIT_REFUSED = (
    "Сейчас менять бюджет может только владелец: окно утверждения закрыто или бюджет уже утверждён."
)
APPROVE_REFUSED = "Утвердить бюджет может только владелец семьи."
NOTHING_TO_APPROVE = (
    f"Бюджета на этот месяц ещё нет: сначала задайте лимиты кнопкой «{LIMIT_BUTTON}»."
)
NO_LIMITS_YET = f"Лимитов пока нет. Задайте их кнопкой «{LIMIT_BUTTON}»."
NO_EXPENSE_CATEGORIES = "Категорий расходов пока нет."
LIMIT_AMOUNT_INVALID = "Нужна сумма больше нуля, например 800 или 120.50."


def ask_limit_category(month: str) -> str:
    return f"Для какой категории задать лимит на {month.lower()}?"


def ask_limit_amount(category: str) -> str:
    return f"Сколько можно потратить на «{category}» за месяц? Напишите сумму, например 800."


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
ASK_ACCOUNT_NAME = "Как назвать счёт? Выберите внизу или напишите своё, например «Копилка»."
ACCOUNT_NAME_INVALID = "Название — от 1 до 100 символов. Напишите другое."
ASK_ACCOUNT_CURRENCY = "В какой валюте этот счёт?"
ASK_ACCOUNT_KIND = "Счёт личный или общий для всей семьи? Общий видят и пополняют все участники."
CHOOSE_ACCOUNT_KIND = f"Выберите кнопкой: «{menu.PERSONAL}» или «{menu.SHARED}»."


def account_created(name: str, currency: str, shared: bool) -> str:
    kind = "Общий счёт" if shared else "Счёт"
    return f"{kind} «{name}» в {currency} создан."


def account_opened(name: str, currency: str, shared: bool) -> str:
    """After the dialog: the result and what to do next."""
    return f"{account_created(name, currency, shared)}\n{FIRST_ENTRY_STEP}"


SHARED_ACCOUNT_REFUSED = "Общий счёт может открыть только владелец семьи."

ASK_LINK_CODE = (
    "Если вы уже зарегистрированы в сервисе с email и паролем, этот Telegram можно "
    "привязать к тому аккаунту.\n"
    "Получите код в API (POST /me/telegram-link-code) и пришлите его сюда."
)

INVITE_REFUSED = "Приглашать в семью может только владелец."


INVITE_HOWTO = (
    "Перешлите следующее сообщение тому, кого зовёте в семью. "
    "Ссылка сработает один раз и действует 48 часов."
)


def invite(link: str) -> str:
    return f"Присоединяйся к нашему семейному бюджету: {link}"


PRESS_GET_CODE = f"Нажмите «{menu.GET_CODE}» или «{menu.CANCEL}»."


def credentials_intro(docs_url: str | None) -> str:
    where = f" ({docs_url})" if docs_url else ""
    return (
        "Для бота пароль не нужен: бот узнаёт вас по Telegram.\n"
        "Email и пароль нужны, только чтобы работать с сервисом напрямую через API.\n\n"
        "Как их задать:\n"
        f"1. Нажмите «{menu.GET_CODE}»: бот пришлёт одноразовый код на 10 минут.\n"
        f"2. Откройте документацию API{where} и найдите POST /auth/credentials.\n"
        "3. Нажмите «Try it out», впишите код, email и пароль, затем «Execute».\n\n"
        "Пароль в этот чат не пишите: бот его никогда не спрашивает."
    )


def credentials_code(code: str) -> str:
    return (
        f"Ваш код: {code}. Действует 10 минут.\n"
        "Впишите его вместе с email и паролем в POST /auth/credentials. "
        "Пароль в этот чат не пишите."
    )
