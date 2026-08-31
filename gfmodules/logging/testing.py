"""Test helpers for applications using this library, free of any test runner.

Records are rendered as they are emitted, because the request context lives in
context variables the formatter reads at emit time. Format afterwards and the
context has already been unbound.
"""

import json
import logging
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from gfmodules.logging.context import register_context_fields
from gfmodules.logging.events import EventCatalogue, LogEvent, missing_events, set_strict_fields, unset_event_ids
from gfmodules.logging.filters import AppFilter, PublicInspectFilter, SiemFilter
from gfmodules.logging.formatter import JsonFormatter
from gfmodules.logging.lifecycle import record_shutdown_reason, reset_shutdown_reason, shutdown_reason
from gfmodules.logging.loggers import DEFAULT_LOGGER_ROOT, active_logger_root, register_logger_root
from gfmodules.logging.registry import clear_access_logs, clear_catalogue
from gfmodules.logging.streams import LoggingStreams

__all__ = [
    "CapturedRecord",
    "CapturedRecords",
    "assert_catalogue_complete",
    "assert_event_emitted",
    "assert_fields_absent",
    "capture_records",
    "capture_stream",
    "detached_loggers",
    "recorded_shutdown_reason",
    "reset_for_tests",
]

_STREAM_FILTERS: dict[LoggingStreams, logging.Filter] = {
    LoggingStreams.APP: AppFilter(),
    LoggingStreams.SIEM: SiemFilter(),
    LoggingStreams.PUBLIC_INSPECT: PublicInspectFilter(),
}


@dataclass
class CapturedRecord:
    """One emitted record, with the JSON the log server would have received."""

    record: logging.LogRecord
    payload: dict[str, Any]

    @property
    def event_id(self) -> str | None:
        value = self.payload["event_id"]
        return str(value) if value is not None else None

    @property
    def message(self) -> dict[str, Any]:
        return dict(self.payload["message"])

    @property
    def level(self) -> str:
        return str(self.payload["level"])

    @property
    def description(self) -> str:
        return str(self.payload["event_description"])


@dataclass
class CapturedRecords:
    entries: list[CapturedRecord] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Any:
        return iter(self.entries)

    def for_event(self, event: LogEvent) -> list[CapturedRecord]:
        return [entry for entry in self.entries if entry.event_id == event.event_id]

    def for_stream(self, stream: LoggingStreams) -> list[CapturedRecord]:
        stream_filter = _STREAM_FILTERS[stream]
        return [entry for entry in self.entries if stream_filter.filter(entry.record)]


class _CaptureHandler(logging.Handler):
    """Marks a handler as belonging to a capture rather than to the application.

    Captures detach the real handlers so nothing reaches a live syslog socket,
    but leave each other attached, so two captures can observe one record.
    """


class _CapturingHandler(_CaptureHandler):
    def __init__(self, captured: CapturedRecords) -> None:
        super().__init__()
        self.captured = captured
        self._formatter = JsonFormatter(include_traces=True)

    def emit(self, record: logging.LogRecord) -> None:
        self.captured.entries.append(CapturedRecord(record=record, payload=json.loads(self._formatter.format(record))))


def detached_loggers() -> tuple[str, ...]:
    """Loggers the dict config detaches from the root logger.

    A capture on root would miss everything under them, so captures reconnect
    them for the duration.
    """
    return (active_logger_root(), "uvicorn", "uvicorn.error")


@contextmanager
def _capturing(handler: logging.Handler, logger_names: tuple[str, ...], level: int) -> Generator[None]:
    if logger_names:
        targets = [logging.getLogger(name) for name in logger_names]
        reattach: list[logging.Logger] = []
    else:
        targets = [logging.getLogger()]
        reattach = [logging.getLogger(name) for name in detached_loggers()]

    saved = [(log, log.handlers, log.level, log.propagate) for log in (*targets, *reattach)]
    for log in targets:
        log.handlers = [*(attached for attached in log.handlers if isinstance(attached, _CaptureHandler)), handler]
        log.setLevel(level)
    for log in reattach:
        log.handlers = [attached for attached in log.handlers if isinstance(attached, _CaptureHandler)]
        log.propagate = True
        log.setLevel(level)
    try:
        yield
    finally:
        for log, handlers, log_level, propagate in saved:
            log.handlers, log.level, log.propagate = handlers, log_level, propagate


@contextmanager
def capture_records(*logger_names: str, level: int = logging.DEBUG) -> Generator[CapturedRecords]:
    captured = CapturedRecords()
    with _capturing(_CapturingHandler(captured), logger_names, level):
        yield captured


class _StreamCapturingHandler(_CaptureHandler):
    def __init__(self, messages: list[dict[str, Any]], stream: LoggingStreams) -> None:
        super().__init__()
        self.messages = messages
        self._formatter = JsonFormatter(include_traces=False, stream=stream)
        self._filter = _STREAM_FILTERS[stream]

    def emit(self, record: logging.LogRecord) -> None:
        if self._filter.filter(record):
            self.messages.append(dict(json.loads(self._formatter.format(record))["message"]))


@contextmanager
def capture_stream(stream: LoggingStreams, *logger_names: str) -> Generator[list[dict[str, Any]]]:
    """Drives the stream's real filter and its stream-bound formatter, so the
    per-event field allow-list is genuinely exercised.
    """
    messages: list[dict[str, Any]] = []
    with _capturing(_StreamCapturingHandler(messages, stream), logger_names, logging.DEBUG):
        yield messages


@contextmanager
def recorded_shutdown_reason(reason: str) -> Generator[None]:
    previous = shutdown_reason()
    record_shutdown_reason(reason)
    try:
        yield
    finally:
        record_shutdown_reason(previous)


def reset_for_tests() -> None:
    """Undo the process-wide state ``configure()`` registers.

    The handlers ``dictConfig`` installs are left in place: a suite that
    configures per test replaces them, and one that configures once keeps them.
    """
    clear_catalogue()
    clear_access_logs()
    register_context_fields(())
    register_logger_root(DEFAULT_LOGGER_ROOT)
    reset_shutdown_reason()
    set_strict_fields(False)


def assert_catalogue_complete(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> None:
    """A missing slot, or one inheriting routing without an id of its own, cannot
    be caught by a type checker, so this is what moves the failure from boot into CI.
    """
    missing = missing_events(catalogue, access_logs=access_logs)
    assert not missing, f"{catalogue.__name__} does not define required events: {', '.join(missing)}"

    unset = unset_event_ids(catalogue, access_logs=access_logs)
    assert not unset, f"{catalogue.__name__} declares events with no event id: {', '.join(unset)}"


def assert_event_emitted(
    captured: CapturedRecords,
    event: LogEvent,
    **fields: Any,
) -> CapturedRecord:
    """The record has to carry these fields, but may carry more."""
    matches = captured.for_event(event)
    assert matches, f"no record emitted with event id {event.event_id}"

    for entry in matches:
        if all(entry.message.get(key) == value for key, value in fields.items()):
            return entry

    raise AssertionError(
        f"event {event.event_id} was emitted, but none carried {fields}; got {[m.message for m in matches]}"
    )


def assert_fields_absent(messages: Iterable[dict[str, Any]], *names: str) -> None:
    for message in messages:
        leaked = sorted(set(names) & set(message))
        assert not leaked, f"fields {leaked} reached a stream they are not allow-listed for"
