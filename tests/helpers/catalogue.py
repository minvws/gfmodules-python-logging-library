"""Event catalogues used across the tests, standing in for an application's own."""

import logging

from gfmodules.logging.events import EventCatalogue, LogEvent
from gfmodules.logging.streams import LoggingStreams

_APP = LoggingStreams.APP
_SIEM = LoggingStreams.SIEM


class CompleteCatalogue(EventCatalogue):
    SYS_APP_STARTED = LogEvent("100601", logging.INFO, (_APP,), {_APP: ("version", "config_path")})
    SYS_APP_STOPPED = LogEvent(
        "100602",
        logging.INFO,
        (_APP, _SIEM),
        {_APP: ("shutdown_reason", "last_exception_type"), _SIEM: ("shutdown_reason",)},
    )
    SYS_APP_CRASHED = LogEvent(
        "100602",
        logging.CRITICAL,
        (_APP, _SIEM),
        {_APP: ("shutdown_reason", "last_exception_type"), _SIEM: ("shutdown_reason",)},
    )
    SYS_UNHANDLED_EXCEPTION = LogEvent(
        "100604",
        logging.ERROR,
        (_APP, _SIEM),
        {_APP: ("exception_type", "endpoint", "method"), _SIEM: ("exception_type", "endpoint", "method")},
    )
    SYS_MISSING_CORRELATION_ID = LogEvent(
        "100606",
        logging.ERROR,
        (_APP, _SIEM),
        {_APP: ("endpoint", "method"), _SIEM: ("endpoint", "method")},
    )
    ACCESS_REQUEST = LogEvent("094500", logging.INFO, (_APP,), {_APP: ("endpoint", "method", "status_code")})

    RESOURCE_CREATED = LogEvent(
        "100607",
        logging.INFO,
        (_APP, _SIEM),
        {_APP: ("owner_id", "resource_id", "created_by"), _SIEM: ("resource_id",)},
    )

    access_event_id = {
        ("POST", "/resources"): "100700",
        ("DELETE", "/resources/{id}"): "100702",
    }


class IncompleteCatalogue(EventCatalogue):
    SYS_APP_STARTED = LogEvent("100601", logging.INFO, (_APP,))
    SYS_APP_STOPPED = LogEvent("100602", logging.INFO, (_APP,))
    SYS_APP_CRASHED = LogEvent("100602", logging.CRITICAL, (_APP,))
    ACCESS_REQUEST = LogEvent("094500", logging.INFO, (_APP,))
