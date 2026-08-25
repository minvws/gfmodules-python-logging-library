import logging
from collections.abc import Iterator

import pytest

from fastapi_app import service
from fastapi_app.app import setup_logging
from fastapi_app.config import Settings


@pytest.fixture(autouse=True)
def configured() -> Iterator[None]:
    """Configure logging as startup would, then put the logging tree back.

    ``configure()`` calls ``dictConfig``, which rewires logging process wide, so
    a suite that leaves it in place changes how every later test behaves.
    """
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)

    setup_logging(Settings(), strict_fields=True)

    yield

    root.handlers, root.level = saved


@pytest.fixture(autouse=True)
def empty_store() -> None:
    """Ordinary application state, unrelated to logging."""
    service._RESOURCES.clear()
