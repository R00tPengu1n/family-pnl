"""Notification texts and the delivery retry schedule."""

from datetime import timedelta

import pytest

from family_pnl.domain.notifications import (
    MAX_DELIVERY_ATTEMPTS,
    gives_up,
    retry_delay,
    threshold_message,
)


@pytest.mark.parametrize(
    ("failed", "delay"),
    [
        (1, timedelta(minutes=1)),
        (2, timedelta(minutes=2)),
        (3, timedelta(minutes=4)),
        (9, timedelta(minutes=256)),
        (10, timedelta(hours=6)),
        (30, timedelta(hours=6)),
    ],
)
def test_the_retry_delay_doubles_up_to_six_hours(failed: int, delay: timedelta) -> None:
    assert retry_delay(failed) == delay


def test_delivery_is_given_up_after_ten_failures() -> None:
    assert MAX_DELIVERY_ATTEMPTS == 10
    assert gives_up(9) is False
    assert gives_up(10) is True


def message(threshold: int, spent: str) -> str:
    return threshold_message(
        month="2026-10",
        category="Продукты",
        threshold=threshold,
        spent=spent,
        limit="100.00",
        currency="BYN",
    )


def test_the_80_percent_message() -> None:
    assert message(80, "80.00") == (
        "Бюджет 2026-10, «Продукты»: потрачено 80.00 из 100.00 BYN — 80% лимита."
    )


@pytest.mark.parametrize("threshold", [100, 120])
def test_the_100_percent_message_says_the_limit_is_used_up(threshold: int) -> None:
    assert message(threshold, "120.00") == (
        "Бюджет 2026-10, «Продукты»: лимит исчерпан — потрачено 120.00 из 100.00 BYN."
    )


def test_below_100_percent_the_share_is_named() -> None:
    assert message(99, "99.00").endswith("— 99% лимита.")
