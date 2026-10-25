"""Quick entry: one message is one income or expense.

    кофе 5.50             expense, 5.50 in the member's input currency
    такси 300 rub         expense, 300 RUB
    +зарплата 2500 byn    income, 2500 BYN
    обед 12,5р            a comma works as the decimal point; the currency may be attached

The text before the amount is the category as typed; the bot matches it to a category.
A leading `+` makes it an income. Amounts are parsed straight into `Decimal`.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

# Currency words and signs as people type them, in lower case.
CURRENCY_ALIASES = {
    "RUB": ("rub", "rur", "р", "р.", "руб", "руб.", "рубль", "рубля", "рублей", "₽"),
    "BYN": ("byn", "br", "бел", "бр", "бел.", "белруб"),
    "USD": ("usd", "$", "дол", "долл", "доллар", "доллара", "долларов"),
}
_CURRENCY = {alias: code for code, aliases in CURRENCY_ALIASES.items() for alias in aliases}
# At most twelve digits before the point: NUMERIC(14, 2) in the API.
_AMOUNT = re.compile(r"(?P<amount>\d{1,12}(?:[.,]\d+)?)")
_SIGN_FIRST = re.compile(r"(?P<sign>\$)(?P<rest>.+)")


class EntryError(ValueError):
    """The message is not a quick entry; the text says why, in Russian."""


@dataclass(frozen=True, slots=True)
class Entry:
    income: bool
    category: str
    amount: Decimal
    currency: str | None  # None: the member's input currency


def parse_entry(text: str) -> Entry:
    words = text.split()
    income = bool(words) and words[0].startswith("+")
    if income:
        words[0] = words[0][1:]
        words = [word for word in words if word]
    currency = None
    if len(words) > 1 and words[-1].lower() in _CURRENCY:
        currency = _CURRENCY[words.pop().lower()]
    if not words:
        raise EntryError("Напишите, на что и сколько: «кофе 5.50».")
    amount, attached = _amount(words.pop())
    if attached is not None:
        if currency is not None:
            raise EntryError("Валюта указана дважды.")
        currency = attached
    category = " ".join(words)
    if not category:
        raise EntryError("Не хватает категории: «кофе 5.50».")
    return Entry(income=income, category=category, amount=amount, currency=currency)


def _amount(word: str) -> tuple[Decimal, str | None]:
    """The amount of the last word, and a currency written right before or after it."""
    sign_first = _SIGN_FIRST.fullmatch(word)
    if sign_first:
        word = sign_first["rest"] + sign_first["sign"]
    match = _AMOUNT.match(word)
    suffix = word[match.end() :].lower() if match else ""
    if match is None or (suffix and suffix not in _CURRENCY):
        raise EntryError("Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub».")
    amount = Decimal(match["amount"].replace(",", "."))
    if amount != amount.quantize(Decimal("0.01")):
        raise EntryError("Не больше двух знаков после запятой.")
    if amount <= 0:
        raise EntryError("Сумма должна быть больше нуля.")
    return amount.quantize(Decimal("0.01")), _CURRENCY.get(suffix) if suffix else None
