"""The logger tree the stream handlers are attached to.

A record logged outside this tree reaches the debug stream and nothing else.
"""

import logging

from gfmodules.logging.streams import LoggingStreams

DEFAULT_LOGGER_ROOT = "app"

_logger_root = DEFAULT_LOGGER_ROOT
_reported_outside_root: set[str] = set()


def register_logger_root(name: str) -> None:
    global _logger_root
    if not name or name.startswith(".") or name.endswith("."):
        raise ValueError(f"invalid logger root {name!r}")
    _logger_root = name
    _reported_outside_root.clear()


def active_logger_root() -> str:
    return _logger_root


def access_logger_name() -> str:
    return f"{_logger_root}.access"


def internal_logger_name() -> str:
    """Where the library logs events it emits on its own behalf."""
    return f"{_logger_root}.internal"


def within_root(name: str) -> bool:
    """Whether records logged here reach the stream handlers at all."""
    return name == _logger_root or name.startswith(f"{_logger_root}.")


def warn_on_app_stream(message: str, *args: object) -> None:
    """Warn where an operator watching a stream is looking, not on the debug stream alone."""
    logging.getLogger(internal_logger_name()).warning(message, *args, extra={"stream": [LoggingStreams.APP]})


def report_outside_root(name: str) -> None:
    """Warn once, because otherwise the failure is silent and total: no error,
    no dropped record count, just a stream that stays empty.
    """
    if name in _reported_outside_root:
        return
    _reported_outside_root.add(name)
    warn_on_app_stream(
        "logger %s is outside the %s tree, so its events reach the debug stream only",
        name,
        _logger_root,
    )
