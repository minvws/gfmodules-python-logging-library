"""Subclassing ``DefaultEventCatalogue`` inherits the routing for the events the
library emits on the application's behalf, leaving this application to supply the
ids its system numbers them with, and to declare its own events.
"""

import logging

from gfmodules.logging import DefaultEventCatalogue, LogEvent, LoggingStreams

APP = LoggingStreams.APP
SIEM = LoggingStreams.SIEM

Base = DefaultEventCatalogue


class Log(Base):
    # The system events: this system's ids, the library's routing. Leaving one
    # out fails in configure(), naming the slot.
    SYS_APP_STARTED = Base.SYS_APP_STARTED.with_id("100601")
    SYS_APP_STOPPED = Base.SYS_APP_STOPPED.with_id("100602")
    # No dedicated id for a crash, so it shares the stopped one. They are told
    # apart by level and by shutdown_reason.
    SYS_APP_CRASHED = Base.SYS_APP_CRASHED.with_id("100602")
    SYS_UNHANDLED_EXCEPTION = Base.SYS_UNHANDLED_EXCEPTION.with_id("100604")
    ACCESS_REQUEST = Base.ACCESS_REQUEST.with_id("094500")

    # replace() where more than the id differs: this application reports a
    # missing correlation id to SIEM as well.
    SYS_MISSING_CORRELATION_ID = Base.SYS_MISSING_CORRELATION_ID.replace(
        event_id="100606",
        streams=(APP, SIEM),
        fields={APP: ("endpoint", "method"), SIEM: ("endpoint", "method")},
    )

    # SIEM is allow-listed for resource_id alone: it is the identifier an
    # auditor needs, and owner_id and created_by have no business being there.
    RESOURCE_CREATED = LogEvent(
        "100700",
        logging.INFO,
        (APP, SIEM),
        {APP: ("resource_id", "owner_id", "created_by"), SIEM: ("resource_id",)},
    )
    RESOURCE_DELETED = LogEvent(
        "100701",
        logging.INFO,
        (APP, SIEM),
        {APP: ("resource_id", "reason"), SIEM: ("resource_id",)},
    )
    LOOKUP_REJECTED = LogEvent("100702", logging.WARNING, (APP,), {APP: ("resource_id", "error_reason")})

    # A slot may alias another event where the trigger has no dedicated id.
    LOOKUP_MALFORMED = LOOKUP_REJECTED

    access_event_id = {
        ("POST", "/resources"): "100710",
        ("DELETE", "/resources/{resource_id}"): "100711",
    }
