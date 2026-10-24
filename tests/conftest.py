import logging
from collections.abc import Iterator

import pytest
import structlog


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
