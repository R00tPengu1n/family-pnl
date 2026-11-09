"""The reply-keyboard menu: button labels and the keyboards of the menu and the dialogs.

Keyboards are rows of button texts; `keyboards.py` turns them into Telegram markup. A
menu button is matched by its exact text, so a label is changed here and nowhere else.
"""

Rows = tuple[tuple[str, ...], ...]

RECORD = "➕ Записать"
TOP_UP = "💵 Пополнить"
TRANSFER = "🔁 Перевод"
BALANCE = "💰 Баланс"
REPORT = "📊 Отчёт"
BUDGET = "📅 Бюджет"
NEW_ACCOUNT = "🏦 Новый счёт"
SETTINGS = "⚙️ Настройки"
HELP = "❓ Помощь"

DISPLAY_CURRENCY = "💱 Валюта отчётов"
INPUT_CURRENCY = "⌨️ Валюта ввода"
INVITE = "👥 Пригласить в семью"
LINK = "🔗 Привязать аккаунт"
CREDENTIALS = "🔑 Email и пароль"
BACK = "⬅️ Назад"

CANCEL = "Отмена"
PERSONAL = "Личный"
SHARED = "Общий"
GET_CODE = "Получить код"
ACCOUNT_NAMES = ("Карта", "Наличные")

MAIN: Rows = (
    (RECORD, TOP_UP),
    (TRANSFER, BALANCE),
    (REPORT, BUDGET),
    (NEW_ACCOUNT, SETTINGS),
    (HELP,),
)
SETTINGS_MENU: Rows = (
    (DISPLAY_CURRENCY, INPUT_CURRENCY),
    (INVITE,),
    (LINK, CREDENTIALS),
    (BACK,),
)
CANCEL_ONLY: Rows = ((CANCEL,),)
ACCOUNT_NAME: Rows = (ACCOUNT_NAMES, (CANCEL,))
# The codes of reports.CURRENCIES; not imported, so messages can import this module.
CURRENCY: Rows = (("BYN", "RUB", "USD"), (CANCEL,))
ACCOUNT_KIND: Rows = ((PERSONAL, SHARED), (CANCEL,))
PASSWORD_CONFIRM: Rows = ((GET_CODE,), (CANCEL,))


def account_label(account: dict[str, str | bool]) -> str:
    """An account on a button: «Карта · BYN», «Копилка · BYN · общий»."""
    label = f"{account['name']} · {account['currency']}"
    return f"{label} · общий" if account["shared"] else label


def choices(options: list[str], per_row: int = 2) -> Rows:
    """Options as rows of `per_row` buttons, then "Отмена"."""
    rows = tuple(tuple(options[i : i + per_row]) for i in range(0, len(options), per_row))
    return (*rows, (CANCEL,))
