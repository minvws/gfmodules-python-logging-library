import logging
import signal
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import FrameType, TracebackType
from typing import Any

from gfmodules.logging.events import EventCatalogue
from gfmodules.logging.loggers import internal_logger_name
from gfmodules.logging.registry import resolve_catalogue

GRACEFUL = "graceful"
CRASH = "crash"


def _logger() -> logging.Logger:
    return logging.getLogger(internal_logger_name())


_shutdown_reason = GRACEFUL


def shutdown_reason() -> str:
    """Why the process is shutting down: graceful, crash, or signal:<NAME>."""
    return _shutdown_reason


def record_shutdown_reason(reason: str) -> None:
    global _shutdown_reason
    _shutdown_reason = reason


def reset_shutdown_reason() -> None:
    record_shutdown_reason(GRACEFUL)


def install_excepthook(logger: logging.Logger, catalogue: type[EventCatalogue] | None = None) -> None:
    """Without this Python prints the traceback to stderr, where it leaks into
    the stdout logs instead of staying in the debug stream.
    """

    def hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        record_shutdown_reason(CRASH)
        events = resolve_catalogue(catalogue)
        events.event(
            logger,
            events.SYS_APP_CRASHED,
            "application crashed: uncaught exception",
            shutdown_reason=shutdown_reason(),
            last_exception_type=exc_type.__name__,
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = hook


def install_signal_handlers(signals: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)) -> None:
    """Delegates to the handler already installed, typically uvicorn's, so
    graceful shutdown keeps working.
    """
    for sig in signals:
        try:
            previous = signal.getsignal(sig)
        except (ValueError, OSError) as exc:
            _logger().warning("could not read the existing handler for %s: %s", sig.name, exc)
            continue

        def make_handler(signum: signal.Signals, prev: Any) -> Any:
            def handler(raised: int, frame: FrameType | None) -> None:
                record_shutdown_reason(f"signal:{signal.Signals(signum).name}")
                if callable(prev):
                    prev(raised, frame)

            return handler

        try:
            signal.signal(sig, make_handler(sig, previous))
        except (ValueError, OSError) as exc:
            # Silence would cost the shutdown reason: a killed process would report a graceful stop.
            _logger().warning("could not install a handler for %s: %s", sig.name, exc)


@asynccontextmanager
async def lifespan_logging(
    logger: logging.Logger,
    *,
    version: str,
    config_path: str | None = None,
    catalogue: type[EventCatalogue] | None = None,
    **fields: Any,
) -> AsyncGenerator[None]:
    """Extra keyword arguments are reported on the started event. Nothing is
    emitted on the way out of a crash: the excepthook has already reported it.
    """
    events = resolve_catalogue(catalogue)
    events.event(
        logger,
        events.SYS_APP_STARTED,
        "application started",
        version=version,
        config_path=config_path,
        **fields,
    )
    try:
        yield
    finally:
        if shutdown_reason() != CRASH:
            events.event(
                logger,
                events.SYS_APP_STOPPED,
                "application stopped",
                shutdown_reason=shutdown_reason(),
            )
