"""Per-request logging context.

One :class:`contextvars.ContextVar` holding a mapping, rather than a variable
per field, so applications can declare fields the library never hears about.
"""

import logging
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)

UNSET = "-"

REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_TRACE_ID_HEADER = "X-Client-Trace-ID"
CORRELATION_ID_HEADER = "X-GF-Correlation-ID"
CLIENT_IP_HEADER = "X-Forwarded-For"
USER_AGENT_HEADER = "User-Agent"

_SAFE_HEADER_VALUE = re.compile(r"[^a-zA-Z0-9\-_]")
_MAX_HEADER_LENGTH = 64
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_FREE_TEXT_LENGTH = 256


def sanitize_header_value(value: str) -> str:
    return _SAFE_HEADER_VALUE.sub("", value)[:_MAX_HEADER_LENGTH] or UNSET


def sanitize_free_text(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)[:_MAX_FREE_TEXT_LENGTH] or UNSET


@dataclass(frozen=True)
class ContextField:
    """``header`` is ``None`` for a field the middleware derives from the
    request itself rather than reading off a header. ``sanitize`` turns cleaning
    off altogether; ``sanitizer`` chooses which cleaning applies when it is on.
    """

    name: str
    header: str | None
    sanitize: bool = True
    sanitizer: Callable[[str], str] = sanitize_header_value


REQUEST_ID = ContextField(name="request_id", header=None)
IP = ContextField(name="ip", header=None)
USER_AGENT = ContextField(name="user_agent", header=USER_AGENT_HEADER, sanitizer=sanitize_free_text)
CLIENT_TRACE_ID = ContextField(name="client_trace_id", header=CLIENT_TRACE_ID_HEADER)
CORRELATION_ID = ContextField(name="correlation_id", header=CORRELATION_ID_HEADER)
ENDPOINT = ContextField(name="endpoint", header=None)
METHOD = ContextField(name="method", header=None)

# Order matters: it is the order these keys appear in every emitted record.
STANDARD_FIELDS: tuple[ContextField, ...] = (
    REQUEST_ID,
    IP,
    USER_AGENT,
    CLIENT_TRACE_ID,
    CORRELATION_ID,
    ENDPOINT,
    METHOD,
)

#: Correlation metadata every stream keeps, whatever an event's routing says.
ALWAYS_KEEP_FIELDS: frozenset[str] = frozenset(
    {REQUEST_ID.name, IP.name, USER_AGENT.name, CLIENT_TRACE_ID.name, CORRELATION_ID.name}
)

_fields: tuple[ContextField, ...] = STANDARD_FIELDS
_context_var: ContextVar[Mapping[str, str] | None] = ContextVar("gfmodules_logging_context", default=None)


def register_context_fields(extra: Sequence[ContextField]) -> None:
    seen: dict[str, ContextField] = {field.name: field for field in STANDARD_FIELDS}
    for field in extra:
        if field.name in seen:
            raise ValueError(f"context field {field.name!r} is already declared")
        seen[field.name] = field

    global _fields
    _fields = (*STANDARD_FIELDS, *extra)


def registered_fields() -> tuple[ContextField, ...]:
    return _fields


def extract_context(headers: Mapping[str, str]) -> dict[str, str]:
    lowered = {key.lower(): value for key, value in headers.items()}
    extracted: dict[str, str] = {}
    for field in _fields:
        if field.header is None:
            continue
        value = lowered.get(field.header.lower(), UNSET)
        if not field.sanitize:
            extracted[field.name] = value
            continue
        cleaned = field.sanitizer(value)
        if cleaned != value:
            # The rejected value is not logged: it is the thing that failed the check.
            _logger.debug("value of header %s was altered to satisfy %s", field.header, field.name)
        extracted[field.name] = cleaned
    return extracted


@contextmanager
def bind_context(values: Mapping[str, Any]) -> Generator[None]:
    token = _context_var.set(dict(values))
    try:
        yield
    finally:
        _context_var.reset(token)


@contextmanager
def update_context(values: Mapping[str, Any]) -> Generator[None]:
    """Adds to the bound context instead of replacing it.

    The field still has to be declared through :func:`register_context_fields`,
    or nothing collects it.
    """
    context_mapping = _context_var.get() or {}
    with bind_context({**context_mapping, **values}):
        yield


def collect_context() -> dict[str, str]:
    bound = _context_var.get() or {}
    return {field.name: bound[field.name] for field in _fields if bound.get(field.name, UNSET) != UNSET}


def correlation_headers() -> dict[str, str]:
    """Headers to propagate the current correlation metadata to a downstream call."""
    bound = _context_var.get() or {}
    headers = {}
    for field, header in ((CORRELATION_ID, CORRELATION_ID_HEADER), (CLIENT_TRACE_ID, CLIENT_TRACE_ID_HEADER)):
        value = bound.get(field.name, UNSET)
        if value != UNSET:
            headers[header] = value
    return headers
