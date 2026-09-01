"""Event definitions and the emit helper.

The required slots are annotation-only ``ClassVar``s, so a type checker will not
reject a subclass that leaves one unfilled. :func:`validate_catalogue` is the
guard instead.
"""

import dataclasses
import logging
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self

from gfmodules.logging.context import ALWAYS_KEEP_FIELDS
from gfmodules.logging.loggers import report_outside_root, within_root
from gfmodules.logging.streams import LoggingStreams

#: Spelled out rather than read off the running interpreter
#: stdblib differs across Python versions, and we want a stable set of reserved names.
_STDLIB_RECORD_FIELDS: frozenset[str] = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

#: Field names a record cannot carry: the standard library refuses to overwrite
#: its own ``LogRecord`` attributes, and the last three are this library's.
RESERVED_FIELDS: frozenset[str] = _STDLIB_RECORD_FIELDS | {
    "message",
    "asctime",
    "event_id",
    "stream",
    "field_streams",
}


#: The id of an event whose number the application still has to supply. Event ids
#: differ per system, so the library declares routing and leaves the numbering out.
UNSET_EVENT_ID = ""


@dataclass(frozen=True)
class LogEvent:
    """A single loggable event from the logging spec.

    An empty ``fields`` means no per-field routing at all, so every field
    reaches every stream in ``streams``.
    """

    event_id: str
    level: int
    streams: tuple[LoggingStreams, ...]
    fields: Mapping[LoggingStreams, tuple[str, ...]] = field(default_factory=dict)

    def replace(
        self,
        *,
        event_id: str | None = None,
        level: int | None = None,
        streams: tuple[LoggingStreams, ...] | None = None,
        fields: Mapping[LoggingStreams, tuple[str, ...]] | None = None,
    ) -> Self:
        """A copy with the named attributes changed.

        An application overriding an inherited event states only what differs,
        so the library's routing stays one definition rather than a copy per
        application.
        """
        return dataclasses.replace(
            self,
            event_id=self.event_id if event_id is None else event_id,
            level=self.level if level is None else level,
            streams=self.streams if streams is None else streams,
            fields=self.fields if fields is None else fields,
        )

    def add_fields(
        self,
        fields: Mapping[LoggingStreams, tuple[str, ...]] | None = None,
    ) -> Self:
        """A copy carrying these fields on top of the ones already allow-listed.

        Example::

            event = LogEvent(
                event_id="1234",
                level=logging.INFO,
                streams=(LoggingStreams.APP,),
                fields={LoggingStreams.APP: ("resource_id",)},
            )
            new_event = event.add_fields(fields={LoggingStreams.APP: ("owner_id",)})
            # new_event.fields now contains both "resource_id" and "owner_id" for the APP stream.
        """
        if not fields:
            return self
        merged = {**self.fields}
        for stream, names in fields.items():
            existing = merged.get(stream, ())
            merged[stream] = existing + tuple(name for name in names if name not in existing)
        return self.replace(fields=merged)

    def with_id(self, event_id: str) -> Self:
        """This system's number for an event the library routes."""
        return self.replace(event_id=event_id)


#: The events the library emits on the application's behalf, so every catalogue must fill them.
REQUIRED_EVENTS: tuple[str, ...] = (
    "SYS_APP_STARTED",
    "SYS_APP_STOPPED",
    "SYS_APP_CRASHED",
    "SYS_UNHANDLED_EXCEPTION",
    "SYS_MISSING_CORRELATION_ID",
    "ACCESS_REQUEST",
)

_ACCESS_EVENTS: frozenset[str] = frozenset({"ACCESS_REQUEST"})


def _excused_events(access_logs: bool) -> frozenset[str]:
    return frozenset() if access_logs else _ACCESS_EVENTS


_strict_fields = False


def set_strict_fields(enabled: bool) -> None:
    """Make :func:`emit` reject fields no declared stream will carry.

    Off by default: a typo should not take a request down in production.
    """
    global _strict_fields
    _strict_fields = enabled


def unrouted_fields(event: LogEvent, names: Iterable[str]) -> tuple[str, ...]:
    if not event.fields:
        return ()
    allowed = {name for allow_list in event.fields.values() for name in allow_list} | ALWAYS_KEEP_FIELDS
    return tuple(sorted(set(names) - allowed))


def emit(
    logger: logging.Logger,
    event: LogEvent,
    message: str,
    *,
    fields: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    exc_info: Any = None,
    stacklevel: int = 1,
) -> None:
    """``stacklevel`` follows the stdlib convention: 1 reports this function's
    caller, and a helper wrapping ``emit`` passes 2 to point past itself.
    """
    values = dict(fields) if fields else {}

    reserved = sorted(RESERVED_FIELDS & values.keys())
    if reserved:
        raise ValueError(f"event {event.event_id} names fields a log record reserves: {', '.join(reserved)}")

    if _strict_fields:
        unrouted = unrouted_fields(event, values)
        if unrouted:
            raise ValueError(f"event {event.event_id} routes none of these fields to any stream: {', '.join(unrouted)}")

    if event.streams and not within_root(logger.name):
        report_outside_root(logger.name)

    extra: dict[str, Any] = {
        "event_id": event_id if event_id else event.event_id,
        "stream": list(event.streams),
    }
    if event.fields:
        extra["field_streams"] = event.fields
    extra.update(values)
    logger.log(event.level, message, extra=extra, exc_info=exc_info, stacklevel=stacklevel + 1)


class EventCatalogue:
    SYS_APP_STARTED: ClassVar[LogEvent]
    SYS_APP_STOPPED: ClassVar[LogEvent]
    SYS_APP_CRASHED: ClassVar[LogEvent]
    SYS_UNHANDLED_EXCEPTION: ClassVar[LogEvent]
    SYS_MISSING_CORRELATION_ID: ClassVar[LogEvent]
    ACCESS_REQUEST: ClassVar[LogEvent]

    #: (method, route path) -> event id, for routes with an access id of their own.
    access_event_id: ClassVar[Mapping[tuple[str, str], str]] = {}

    @classmethod
    def event(
        cls,
        logger: logging.Logger,
        event: LogEvent,
        message: str,
        *,
        fields: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        exc_info: Any = None,
        stacklevel: int = 1,
    ) -> None:
        emit(
            logger,
            event,
            message,
            fields=fields,
            event_id=event_id,
            exc_info=exc_info,
            stacklevel=stacklevel + 1,
        )


def missing_events(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> tuple[str, ...]:
    excused = _excused_events(access_logs)
    return tuple(
        name
        for name in REQUIRED_EVENTS
        if name not in excused and not isinstance(getattr(catalogue, name, None), LogEvent)
    )


_APP = LoggingStreams.APP
_SIEM = LoggingStreams.SIEM


class DefaultEventCatalogue(EventCatalogue):
    """The routing for the events the library emits, so an application declares
    only its own events and the ids its system numbers them with.

    Every id here is :data:`UNSET_EVENT_ID`: numbering differs per system, and a
    default number is one an application adopts by accident. Fill them in with
    :meth:`LogEvent.with_id`, or :meth:`LogEvent.replace` where the level,
    streams or field allow-lists differ too::

        class Log(DefaultEventCatalogue):
            SYS_APP_STARTED = DefaultEventCatalogue.SYS_APP_STARTED.with_id("100801")

    :func:`validate_catalogue` rejects an id left unset, so the omission surfaces
    at boot rather than as a record the log server cannot place.
    """

    SYS_APP_STARTED = LogEvent(UNSET_EVENT_ID, logging.INFO, (_APP,), {_APP: ("version", "config_path")})
    SYS_APP_STOPPED = LogEvent(
        UNSET_EVENT_ID,
        logging.INFO,
        (_APP, _SIEM),
        {_APP: ("shutdown_reason", "last_exception_type"), _SIEM: ("shutdown_reason",)},
    )
    SYS_APP_CRASHED = LogEvent(
        UNSET_EVENT_ID,
        logging.CRITICAL,
        (_APP, _SIEM),
        {_APP: ("shutdown_reason", "last_exception_type"), _SIEM: ("shutdown_reason",)},
    )
    SYS_UNHANDLED_EXCEPTION = LogEvent(
        UNSET_EVENT_ID,
        logging.ERROR,
        (_APP, _SIEM),
        {_APP: ("exception_type", "endpoint", "method"), _SIEM: ("exception_type", "endpoint", "method")},
    )
    SYS_MISSING_CORRELATION_ID = LogEvent(UNSET_EVENT_ID, logging.ERROR, (_APP,), {_APP: ("endpoint", "method")})
    ACCESS_REQUEST = LogEvent(
        UNSET_EVENT_ID,
        logging.INFO,
        (_APP,),
        {_APP: ("endpoint", "method", "status_code", "duration_ms", "body", "body_truncated")},
    )


def declared_events(catalogue: type[EventCatalogue]) -> Iterator[tuple[str, LogEvent]]:
    """Every event the catalogue defines, in declaration order, subclass first."""
    seen: set[str] = set()
    for klass in catalogue.__mro__:
        for name, value in vars(klass).items():
            if name not in seen and isinstance(value, LogEvent):
                seen.add(name)
                yield name, value


def unset_event_ids(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> tuple[str, ...]:
    excused = _excused_events(access_logs)
    return tuple(
        sorted(name for name, event in declared_events(catalogue) if not event.event_id and name not in excused)
    )


def reserved_field_names(catalogue: type[EventCatalogue]) -> tuple[str, ...]:
    """The standard library raises at log time for these, so a rarely taken
    branch would otherwise take the process down long after the catalogue was
    written.
    """
    return tuple(
        f"{name}.{field_name}"
        for name, event in declared_events(catalogue)
        for allow_list in event.fields.values()
        for field_name in allow_list
        if field_name in RESERVED_FIELDS
    )


def validate_catalogue(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> None:
    missing = missing_events(catalogue, access_logs=access_logs)
    if missing:
        raise ValueError(f"{catalogue.__name__} does not define required events: {', '.join(missing)}")

    unset = unset_event_ids(catalogue, access_logs=access_logs)
    if unset:
        raise ValueError(f"{catalogue.__name__} declares events with no event id: {', '.join(unset)}. ")

    reserved = reserved_field_names(catalogue)
    if reserved:
        raise ValueError(f"{catalogue.__name__} declares fields a log record reserves: {', '.join(reserved)}")
