"""Call sites for the ``source`` tests.

``source`` must report the module and line that logged the event, so these
helpers have to live outside the library's own modules.
"""

import inspect
import logging

from gfmodules.logging.events import LogEvent, emit
from tests.helpers.catalogue import CompleteCatalogue


def _next_line() -> int:
    frame = inspect.currentframe()
    assert frame is not None and frame.f_back is not None
    return frame.f_back.f_lineno + 1


def emit_directly(logger: logging.Logger, event: LogEvent) -> int:
    expected = _next_line()
    emit(logger, event, "direct")
    return expected


def emit_via_catalogue(logger: logging.Logger, event: LogEvent) -> int:
    expected = _next_line()
    CompleteCatalogue.event(logger, event, "via catalogue")
    return expected


def emit_via_app_wrapper(logger: logging.Logger, event: LogEvent) -> int:
    expected = _next_line()
    _app_wrapper(logger, event)
    return expected


def _app_wrapper(logger: logging.Logger, event: LogEvent) -> None:
    # stacklevel=2 points the record at this function's caller rather than here.
    emit(logger, event, "wrapped", stacklevel=2)
