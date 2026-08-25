"""Subclassing ``DefaultEventCatalogue`` fills the system slots the library
emits on the application's behalf, leaving only the application's own to declare.
"""

import logging

from gfmodules.logging import DefaultEventCatalogue, LogEvent, LoggingStreams

APP = LoggingStreams.APP
SIEM = LoggingStreams.SIEM


class Log(DefaultEventCatalogue):
    SYS_MISSING_CORRELATION_ID = LogEvent("100606", logging.ERROR, (APP,), {APP: ("endpoint", "method")})

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
