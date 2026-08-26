import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from gfmodules.logging.context import ALWAYS_KEEP_FIELDS, collect_context
from gfmodules.logging.events import RESERVED_FIELDS
from gfmodules.logging.streams import LoggingStreams

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _allowed_on(
    record: logging.LogRecord,
    stream: LoggingStreams | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    field_streams: dict[LoggingStreams, tuple[str, ...]] | None = getattr(record, "field_streams", None)
    if stream is None or not field_streams:
        return data
    allowed = set(field_streams.get(stream, ())) | ALWAYS_KEEP_FIELDS
    return {key: value for key, value in data.items() if key in allowed}


def _sanitize_message(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)


def _collect_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in RESERVED_FIELDS}


class JsonFormatter(logging.Formatter):
    """All streams share one syslog channel, so ``stream_id`` and
    ``application_id`` are what let the log server tell records apart.
    """

    def __init__(
        self,
        include_traces: bool = True,
        stream: LoggingStreams | None = None,
        stream_id: str | None = None,
        application_id: str | None = None,
    ) -> None:
        super().__init__()
        self.include_traces = include_traces
        self.stream = stream
        self.stream_id = stream_id
        self.application_id = application_id

    def format(self, record: logging.LogRecord) -> str:
        message: dict[str, Any] = {}

        if record.exc_info and self.include_traces:
            message["exception"] = self.formatException(record.exc_info)
        if record.stack_info and self.include_traces:
            message["stack_info"] = self.formatStack(record.stack_info)

        data = {**collect_context(), **_collect_extras(record)}
        message.update(_allowed_on(record, self.stream, data))

        log_record: dict[str, Any] = {
            "event_id": getattr(record, "event_id", None),
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "event_description": _sanitize_message(record.getMessage()),
            "source": f"{record.module}:{record.lineno}",
        }
        if self.application_id is not None:
            log_record["application_id"] = self.application_id
        if self.stream_id is not None:
            log_record["stream_id"] = self.stream_id
        log_record["message"] = message

        return json.dumps(log_record, default=str)


class PlainTextFormatter(logging.Formatter):
    def __init__(self, stream: LoggingStreams | None = None) -> None:
        super().__init__()
        self.stream = stream

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event_id = getattr(record, "event_id", None) or "-"
        base = f"{timestamp} {record.levelname:<8} {record.name} [{event_id}] {_sanitize_message(record.getMessage())}"

        data = {**collect_context(), **_collect_extras(record)}
        pairs = [f"{key}={value}" for key, value in _allowed_on(record, self.stream, data).items()]

        out = base if not pairs else f"{base} {' '.join(pairs)}"

        if record.exc_info:
            out = f"{out}\n{self.formatException(record.exc_info)}"
        return out
