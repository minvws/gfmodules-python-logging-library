"""Shared logging setup for GFModules Python applications.

``middleware`` and ``exceptions`` are not re-exported here: they need starlette,
an optional extra, so applications import them directly.
"""

import logging
from collections.abc import Sequence
from logging.config import dictConfig

from gfmodules.logging.config import ConfigLogging
from gfmodules.logging.config_builder import LogConfigBuilder
from gfmodules.logging.context import (
    CLIENT_TRACE_ID_HEADER,
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    UNSET,
    ContextField,
    bind_context,
    collect_context,
    correlation_headers,
    register_context_fields,
    update_context,
)
from gfmodules.logging.events import (
    REQUIRED_EVENTS,
    RESERVED_FIELDS,
    UNSET_EVENT_ID,
    DefaultEventCatalogue,
    EventCatalogue,
    LogEvent,
    declared_events,
    emit,
    missing_events,
    reserved_field_names,
    set_strict_fields,
    unset_event_ids,
    validate_catalogue,
)
from gfmodules.logging.filters import AppFilter, PublicInspectFilter, SiemFilter
from gfmodules.logging.formatter import JsonFormatter, PlainTextFormatter
from gfmodules.logging.lifecycle import (
    CRASH,
    GRACEFUL,
    install_excepthook,
    install_signal_handlers,
    lifespan_logging,
    shutdown_reason,
)
from gfmodules.logging.loggers import (
    DEFAULT_LOGGER_ROOT,
    access_logger_name,
    active_logger_root,
    internal_logger_name,
    register_logger_root,
    warn_on_app_stream,
)
from gfmodules.logging.registry import (
    access_logs_enabled,
    active_catalogue,
    register_access_logs,
    register_catalogue,
)
from gfmodules.logging.streams import LoggingStreams

__all__ = [
    "CLIENT_TRACE_ID_HEADER",
    "CORRELATION_ID_HEADER",
    "CRASH",
    "DEFAULT_LOGGER_ROOT",
    "GRACEFUL",
    "REQUEST_ID_HEADER",
    "REQUIRED_EVENTS",
    "RESERVED_FIELDS",
    "UNSET",
    "UNSET_EVENT_ID",
    "AppFilter",
    "ConfigLogging",
    "ContextField",
    "DefaultEventCatalogue",
    "EventCatalogue",
    "JsonFormatter",
    "LogConfigBuilder",
    "LogEvent",
    "LoggingStreams",
    "PlainTextFormatter",
    "PublicInspectFilter",
    "SiemFilter",
    "access_logger_name",
    "access_logs_enabled",
    "active_catalogue",
    "active_logger_root",
    "bind_context",
    "collect_context",
    "configure",
    "correlation_headers",
    "declared_events",
    "emit",
    "install_excepthook",
    "install_signal_handlers",
    "internal_logger_name",
    "lifespan_logging",
    "missing_events",
    "register_access_logs",
    "register_catalogue",
    "register_logger_root",
    "reserved_field_names",
    "set_strict_fields",
    "shutdown_reason",
    "unset_event_ids",
    "update_context",
    "validate_catalogue",
]


def configure(
    *,
    config: ConfigLogging,
    loglevel: str,
    catalogue: type[EventCatalogue],
    extra_context_fields: Sequence[ContextField] = (),
    strict_fields: bool = False,
    logger_root: str = DEFAULT_LOGGER_ROOT,
) -> None:
    """Call once during startup, before anything logs."""
    level = loglevel.upper()
    if level not in logging.getLevelNamesMapping():
        raise ValueError(f"invalid loglevel {level}")

    validate_catalogue(catalogue, access_logs=config.access_logs)
    set_strict_fields(strict_fields)
    register_context_fields(extra_context_fields)
    register_access_logs(config.access_logs)
    register_catalogue(catalogue)
    register_logger_root(logger_root)
    try:
        dictConfig(LogConfigBuilder(logging_config=config, loglevel=level).build())
    except ValueError as exc:
        if not config.syslog_path:
            raise
        # dictConfig names only the handler it could not build, never the setting behind it.
        raise ValueError(f"could not reach the log server at syslog_path {config.syslog_path!r}: {exc}") from exc

    if config.syslog_path and not config.application_id:
        warn_on_app_stream(
            "no application_id is configured, so the log server cannot tell this application's "
            "records from any other's on the shared syslog channel"
        )
