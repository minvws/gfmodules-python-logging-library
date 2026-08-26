import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from gfmodules.logging.formatter import JsonFormatter
from gfmodules.logging.loggers import access_logger_name, internal_logger_name
from gfmodules.logging.registry import register_catalogue
from gfmodules.logging.testing import detached_loggers, reset_for_tests
from tests.helpers.catalogue import CompleteCatalogue


class RecordingHandler(logging.Handler):
    """Records are rendered at emit time, because the request context lives in
    context variables the formatter reads then. Format later and it has already
    been unbound.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.payloads: list[dict[str, Any]] = []
        self._json = JsonFormatter(include_traces=True)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.payloads.append(json.loads(self._json.format(record)))

    def with_event_id(self, event_id: str) -> list[logging.LogRecord]:
        return [record for record in self.records if getattr(record, "event_id", None) == event_id]

    def messages_with_event_id(self, event_id: str) -> list[dict[str, Any]]:
        return [dict(payload["message"]) for payload in self.payloads if payload["event_id"] == event_id]


@pytest.fixture(autouse=True)
def isolate_logging() -> Iterator[None]:
    """Undo anything a test does to the logging tree.

    ``configure()`` calls ``dictConfig``, which rewires loggers process wide, so
    a test that configures the library would change every later one.
    """
    snapshot = {
        name: (list(log.handlers), log.level, log.propagate)
        for name, log in list(logging.Logger.manager.loggerDict.items())
        if isinstance(log, logging.Logger)
    }
    root = logging.getLogger()
    root_state = (list(root.handlers), root.level)

    yield

    root.handlers, root.level = root_state
    for name, log in list(logging.Logger.manager.loggerDict.items()):
        if not isinstance(log, logging.Logger):
            continue
        if name in snapshot:
            log.handlers, log.level, log.propagate = snapshot[name]
        else:
            log.handlers, log.level, log.propagate = [], logging.NOTSET, True


@pytest.fixture(autouse=True)
def reset_library_state() -> Iterator[None]:
    """Keep the module-level registries from leaking between tests.

    Through the helper the library ships, so a consumer's conftest and this one
    stay the same thing.
    """
    yield
    reset_for_tests()


@pytest.fixture
def catalogue() -> type[CompleteCatalogue]:
    register_catalogue(CompleteCatalogue)
    return CompleteCatalogue


@pytest.fixture
def records() -> RecordingHandler:
    """Reconnects the loggers the dict config detaches from root and silences
    their own handlers, so records arrive here exactly once. ``isolate_logging``
    puts the tree back afterwards.
    """
    handler = RecordingHandler()
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)

    for name in (*detached_loggers(), access_logger_name(), internal_logger_name()):
        log = logging.getLogger(name)
        log.handlers = []
        log.propagate = True
        log.setLevel(logging.DEBUG)

    return handler
