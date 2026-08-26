"""The domain layer, which knows nothing about HTTP.

Note what these calls do not pass: no request id, no correlation id, no
endpoint. The middleware bound those, so a call site names only its own fields.
"""

import logging

import gfmodules.logging as gflog
from fastapi_app.events import Log

logger = logging.getLogger("app.resources")


class UnknownResource(Exception):
    """Raised when a lookup names a resource the store does not hold."""


_RESOURCES: dict[str, str] = {}


def create_resource(resource_id: str, owner_id: str, created_by: str) -> None:
    _RESOURCES[resource_id] = owner_id
    gflog.emit(
        logger,
        Log.RESOURCE_CREATED,
        "resource created",
        resource_id=resource_id,
        owner_id=owner_id,
        created_by=created_by,
    )


def delete_resource(resource_id: str, reason: str) -> None:
    if resource_id not in _RESOURCES:
        log_rejected_lookup(resource_id, "unknown resource_id")
        raise UnknownResource(resource_id)

    del _RESOURCES[resource_id]
    gflog.emit(
        logger,
        Log.RESOURCE_DELETED,
        "resource deleted",
        resource_id=resource_id,
        reason=reason,
    )


def log_rejected_lookup(resource_id: str, error_reason: str) -> None:
    """Without ``stacklevel=2`` every rejected lookup would report this line as
    its ``source`` rather than the line that rejected one.
    """
    gflog.emit(
        logger,
        Log.LOOKUP_REJECTED,
        "lookup rejected",
        resource_id=resource_id,
        error_reason=error_reason,
        stacklevel=2,
    )
