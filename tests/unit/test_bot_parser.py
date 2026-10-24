"""Quick entry messages: what is parsed, and what is refused with a reason."""

from decimal import Decimal

import pytest

from family_pnl_bot.parser import CURRENCY_ALIASES, Entry, EntryError, parse_entry


@pytest.mark.parametrize(
    ("text", "entry"),
    [
        # The spec examples.
        ("кофе 5.50", Entry(False, "кофе", Decimal("5.50"), None)),
        ("такси 300 rub", Entry(False, "такси", Decimal("300.00"), "RUB")),
        ("+зарплата 2500 byn", Entry(True, "зарплата", Decimal("2500.00"), "BYN")),
        # Commas, spaces, case and attached currencies.
        ("обед 12,5", Entry(False, "обед", Decimal("12.50"), None)),
        ("обед 12,5р", Entry(False, "обед", Decimal("12.50"), "RUB")),
        ("обед 12.50 РУБ.", Entry(False, "обед", Decimal("12.50"), "RUB")),
        ("книга $15", Entry(False, "книга", Decimal("15.00"), "USD")),
        ("книга 15$", Entry(False, "книга", Decimal("15.00"), "USD")),
        ("книга 15 $", Entry(False, "книга", Decimal("15.00"), "USD")),
        ("  детский   сад  300  бел ", Entry(False, "детский сад", Decimal("300.00"), "BYN")),
        ("+ подарок 50 usd", Entry(True, "подарок", Decimal("50.00"), "USD")),
        ("+Премия 1000", Entry(True, "Премия", Decimal("1000.00"), None)),
        ("кофе 0.01", Entry(False, "кофе", Decimal("0.01"), None)),
        ("дом 999999999999.99", Entry(False, "дом", Decimal("999999999999.99"), None)),
        # The category may contain digits; only the last word is the amount.
        ("маршрутка 15 7", Entry(False, "маршрутка 15", Decimal("7.00"), None)),
    ],
)
def test_quick_entries_are_parsed(text: str, entry: Entry) -> None:
    assert parse_entry(text) == entry


@pytest.mark.parametrize(
    ("currency", "alias"),
    [(currency, alias) for currency, aliases in CURRENCY_ALIASES.items() for alias in aliases],
)
def test_every_currency_alias_works_as_a_word_and_attached(currency: str, alias: str) -> None:
    assert parse_entry(f"кофе 5 {alias}").currency == currency
    assert parse_entry(f"кофе 5{alias}").currency == currency
    assert parse_entry(f"кофе 5 {alias.upper()}").currency == currency


def test_amounts_are_decimal_never_float() -> None:
    entry = parse_entry("кофе 0,10")

    assert type(entry.amount) is Decimal
    assert entry.amount == Decimal("0.10")
    assert str(entry.amount) == "0.10"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "Напишите, на что и сколько: «кофе 5.50»."),
        ("   ", "Напишите, на что и сколько: «кофе 5.50»."),
        ("+", "Напишите, на что и сколько: «кофе 5.50»."),
        ("5.50", "Не хватает категории: «кофе 5.50»."),
        ("5.50 rub", "Не хватает категории: «кофе 5.50»."),
        ("+300", "Не хватает категории: «кофе 5.50»."),
        ("кофе", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе пять", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе 5.50 утром", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе -5", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе 5eur", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе 5.", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе 1e3", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе 1234567890123", "Сумма в конце сообщения: «кофе 5.50» или «такси 300 rub»."),
        ("кофе 5.505", "Не больше двух знаков после запятой."),
        ("кофе 0", "Сумма должна быть больше нуля."),
        ("кофе 0.00", "Сумма должна быть больше нуля."),
        ("кофе 5р rub", "Валюта указана дважды."),
    ],
)
def test_other_messages_are_refused_with_a_reason(text: str, reason: str) -> None:
    with pytest.raises(EntryError) as raised:
        parse_entry(text)

    assert str(raised.value) == reason
