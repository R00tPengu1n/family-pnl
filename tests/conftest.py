import logging
from collections.abc import Iterator

import pytest
import structlog
from argon2 import PasswordHasher

from family_pnl.core import security


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """configure_logging changes process-wide state; give every test a clean slate."""
    managed = [
        logging.getLogger(),
        *(logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access")),
    ]
    saved = [(lg, lg.handlers[:], lg.level, lg.propagate) for lg in managed]
    yield
    structlog.reset_defaults()
    for lg, handlers, level, propagate in saved:
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate = propagate


@pytest.fixture(autouse=True)
def _cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """argon2id with minimal cost: the same algorithm, ~100x faster than production settings.

    Production parameters (64 MiB, 3 passes) would dominate the suite's runtime; the hashing
    behaviour under test (salting, verification, rejection) does not depend on them.
    """
    monkeypatch.setattr(
        security, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )
    security._dummy_hash.cache_clear()
