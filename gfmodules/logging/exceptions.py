"""The logging half of exception handling. Applications own the rest."""

import logging

from starlette.requests import Request

from gfmodules.logging.events import EventCatalogue
from gfmodules.logging.middleware import bind_request_context
from gfmodules.logging.registry import resolve_catalogue


def log_unhandled_exception(
    logger: logging.Logger,
    request: Request,
    exc: Exception,
    *,
    catalogue: type[EventCatalogue] | None = None,
) -> None:
    """Exception handlers run in ``ServerErrorMiddleware``, outside
    ``RequestContextMiddleware``, so the request context has been torn down by
    the time they execute. This rebinds it for the log call, decorated or not.
    """
    events = resolve_catalogue(catalogue)
    with bind_request_context(request):
        events.event(
            logger,
            events.SYS_UNHANDLED_EXCEPTION,
            "unhandled exception",
            exc_info=exc,
            exception_type=type(exc).__name__,
            endpoint=request.url.path,
            method=request.method,
        )
