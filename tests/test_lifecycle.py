import logging
import signal
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from gfmodules.logging.lifecycle import (
    install_excepthook,
    install_signal_handlers,
    lifespan_logging,
    reset_shutdown_reason,
    shutdown_reason,
)
from gfmodules.logging.testing import recorded_shutdown_reason
from tests.conftest import RecordingHandler
from tests.helpers.catalogue import CompleteCatalogue

STARTED = CompleteCatalogue.SYS_APP_STARTED.event_id
STOPPED = CompleteCatalogue.SYS_APP_STOPPED.event_id
CRASHED = CompleteCatalogue.SYS_APP_CRASHED.event_id

pytestmark = pytest.mark.usefixtures("catalogue")


@pytest.fixture(autouse=True)
def clean_shutdown_reason() -> Iterator[None]:
    reset_shutdown_reason()
    yield
    reset_shutdown_reason()


@pytest.fixture
def logger(records: RecordingHandler) -> logging.Logger:
    log = logging.getLogger("tests.lifecycle")
    log.handlers = []
    log.propagate = True
    log.setLevel(logging.DEBUG)
    return log


class TestLifespanLogging:
    async def test_emits_started_before_the_application_runs(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        async with lifespan_logging(logger, version="1.2.3", config_path="/etc/app.conf"):
            assert records.with_event_id(STARTED)

        record = records.with_event_id(STARTED)[0]
        assert record.version == "1.2.3"  # type: ignore[attr-defined]
        assert record.config_path == "/etc/app.conf"  # type: ignore[attr-defined]

    async def test_emits_stopped_after_the_application_finishes(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        async with lifespan_logging(logger, version="1.2.3"):
            assert _stopped_records(records) == []

        assert _stopped_records(records)[0].shutdown_reason == "graceful"  # type: ignore[attr-defined]

    async def test_reports_the_recorded_shutdown_reason(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        async with lifespan_logging(logger, version="1.2.3"):
            _record_signal_shutdown()

        assert _stopped_records(records)[0].shutdown_reason == "signal:SIGTERM"  # type: ignore[attr-defined]

    async def test_a_test_can_set_the_reason_without_reaching_into_the_module(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        with recorded_shutdown_reason("signal:SIGTERM"):
            async with lifespan_logging(logger, version="1.2.3"):
                pass

            assert _stopped_records(records)[0].shutdown_reason == "signal:SIGTERM"  # type: ignore[attr-defined]

        assert shutdown_reason() == "graceful"

    async def test_emits_stopped_even_when_the_application_raises(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        with pytest.raises(RuntimeError):
            async with lifespan_logging(logger, version="1.2.3"):
                raise RuntimeError("startup failed")

        assert _stopped_records(records)

    async def test_stays_quiet_after_a_crash_because_the_excepthook_reported_it(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        async with lifespan_logging(logger, version="1.2.3"):
            _crash(logger)

        # A catalogue may give crashed and stopped the same event id, so they
        # are told apart by level rather than by id.
        assert _stopped_records(records) == []
        assert [r for r in records.with_event_id(CRASHED) if r.levelno == logging.CRITICAL]

    async def test_config_path_is_optional(self, logger: logging.Logger, records: RecordingHandler) -> None:
        async with lifespan_logging(logger, version="1.2.3"):
            pass

        assert records.with_event_id(STARTED)[0].config_path is None  # type: ignore[attr-defined]

    async def test_carries_the_applications_own_fields_on_started(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        async with lifespan_logging(logger, version="1.2.3", read_only_mode=True):
            pass

        assert records.with_event_id(STARTED)[0].read_only_mode is True  # type: ignore[attr-defined]

    async def test_the_applications_own_fields_do_not_leak_onto_stopped(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        """Stopped reports why the process ended, not how it was configured."""
        async with lifespan_logging(logger, version="1.2.3", read_only_mode=True):
            pass

        assert not hasattr(_stopped_records(records)[0], "read_only_mode")


class TestExcepthook:
    def test_logs_the_crash_with_its_traceback(self, logger: logging.Logger, records: RecordingHandler) -> None:
        _crash(logger)

        record = records.with_event_id(CRASHED)[0]
        assert record.levelno == logging.CRITICAL
        assert record.last_exception_type == "ValueError"  # type: ignore[attr-defined]
        assert record.shutdown_reason == "crash"  # type: ignore[attr-defined]
        assert record.exc_info is not None

    def test_records_the_shutdown_reason(self, logger: logging.Logger, records: RecordingHandler) -> None:
        _crash(logger)

        assert shutdown_reason() == "crash"

    def test_leaves_keyboard_interrupt_to_the_default_hook(
        self, logger: logging.Logger, records: RecordingHandler
    ) -> None:
        with _restored_excepthook():
            install_excepthook(logger)
            try:
                raise KeyboardInterrupt()
            except KeyboardInterrupt:
                sys.excepthook(*sys.exc_info())

        assert records.with_event_id(CRASHED) == []
        assert shutdown_reason() == "graceful"


class TestSignalHandlers:
    def test_records_the_signal_that_asked_us_to_stop(self) -> None:
        with _restored_signals():
            install_signal_handlers((signal.SIGTERM,))
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)

        assert shutdown_reason() == "signal:SIGTERM"

    def test_delegates_to_the_handler_that_was_already_installed(self) -> None:
        called: list[int] = []

        with _restored_signals():
            signal.signal(signal.SIGTERM, lambda raised, frame: called.append(raised))
            install_signal_handlers((signal.SIGTERM,))
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)

        assert called == [signal.SIGTERM]

    def test_survives_a_signal_with_no_installed_handler(self) -> None:
        with _restored_signals():
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            install_signal_handlers((signal.SIGTERM,))
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)

        assert shutdown_reason() == "signal:SIGTERM"

    def test_reports_a_handler_it_could_not_install(
        self, records: RecordingHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Silence here would cost the shutdown reason on every signal."""

        def refuse(sig: Any, handler: Any) -> Any:
            raise ValueError("signal only works in main thread")

        with _restored_signals():
            monkeypatch.setattr(signal, "signal", refuse)
            install_signal_handlers((signal.SIGTERM,))
            # Undone inside the block: restoring the signals needs the real one.
            monkeypatch.undo()

        assert any("could not install a handler for SIGTERM" in r.getMessage() for r in records.records)


def _stopped_records(records: RecordingHandler) -> list[logging.LogRecord]:
    """Stopped shares its event id with crashed; level is what separates them."""
    return [r for r in records.with_event_id(STOPPED) if r.levelno == logging.INFO]


def _crash(logger: logging.Logger) -> None:
    with _restored_excepthook():
        install_excepthook(logger)
        try:
            raise ValueError("boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())


def _record_signal_shutdown() -> None:
    with _restored_signals():
        install_signal_handlers((signal.SIGTERM,))
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)


class _restored_excepthook:
    def __enter__(self) -> None:
        self.previous = sys.excepthook

    def __exit__(self, *exc: Any) -> None:
        sys.excepthook = self.previous


class _restored_signals:
    def __enter__(self) -> None:
        self.previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def __exit__(self, *exc: Any) -> None:
        for sig, handler in self.previous.items():
            signal.signal(sig, handler)
