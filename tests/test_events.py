import logging
from typing import Any

import pytest

from gfmodules.logging.events import (
    _STDLIB_RECORD_FIELDS,
    REQUIRED_EVENTS,
    RESERVED_FIELDS,
    DefaultEventCatalogue,
    EventCatalogue,
    LogEvent,
    emit,
    missing_events,
    reserved_field_names,
    set_strict_fields,
    unrouted_fields,
    validate_catalogue,
)
from gfmodules.logging.streams import LoggingStreams
from tests.helpers import emitters
from tests.helpers.catalogue import CompleteCatalogue, IncompleteCatalogue


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def handler() -> RecordingHandler:
    return RecordingHandler()


@pytest.fixture
def logger(handler: RecordingHandler, request: Any) -> logging.Logger:
    log = logging.getLogger(f"tests.events.{request.node.name}")
    log.handlers = [handler]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    return log


class TestEmit:
    def test_stamps_the_event_id_and_streams_on_the_record(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        emit(logger, CompleteCatalogue.RESOURCE_CREATED, "resource created", resource_id="12345")

        record = handler.records[0]
        assert record.event_id == "100607"  # type: ignore[attr-defined]
        assert record.stream == [LoggingStreams.APP, LoggingStreams.SIEM]  # type: ignore[attr-defined]
        assert record.resource_id == "12345"  # type: ignore[attr-defined]
        assert record.getMessage() == "resource created"

    def test_logs_at_the_level_the_event_declares(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        emit(logger, CompleteCatalogue.SYS_APP_CRASHED, "crashed")

        assert handler.records[0].levelno == logging.CRITICAL

    def test_attaches_field_streams_when_the_event_declares_routing(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        emit(logger, CompleteCatalogue.RESOURCE_CREATED, "resource created")

        assert handler.records[0].field_streams == CompleteCatalogue.RESOURCE_CREATED.fields  # type: ignore[attr-defined]

    def test_omits_field_streams_when_the_event_declares_none(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        emit(logger, LogEvent("1", logging.INFO, (LoggingStreams.APP,)), "no routing")

        assert not hasattr(handler.records[0], "field_streams")

    def test_an_explicit_event_id_overrides_the_events_own(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        emit(logger, CompleteCatalogue.ACCESS_REQUEST, "access", event_id="100700")

        assert handler.records[0].event_id == "100700"  # type: ignore[attr-defined]

    def test_falls_back_to_the_events_id_when_the_override_is_none(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        emit(logger, CompleteCatalogue.ACCESS_REQUEST, "access", event_id=None)

        assert handler.records[0].event_id == "094500"  # type: ignore[attr-defined]

    def test_carries_exception_information(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        exc = ValueError("boom")

        emit(logger, CompleteCatalogue.SYS_UNHANDLED_EXCEPTION, "failed", exc_info=exc)

        assert handler.records[0].exc_info is not None
        assert handler.records[0].exc_info[1] is exc

    def test_extra_fields_may_shadow_nothing_builtin(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        emit(logger, CompleteCatalogue.ACCESS_REQUEST, "access", status_code=204, duration_ms=7)

        assert handler.records[0].status_code == 204  # type: ignore[attr-defined]
        assert handler.records[0].duration_ms == 7  # type: ignore[attr-defined]


class TestSourceResolution:
    """``source`` must name the call site, not the library's own wrapper."""

    def test_emit_reports_its_caller(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        expected_line = emitters.emit_directly(logger, CompleteCatalogue.RESOURCE_CREATED)

        record = handler.records[0]
        assert record.module == "emitters"
        assert record.lineno == expected_line

    def test_the_catalogue_helper_reports_its_caller(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        expected_line = emitters.emit_via_catalogue(logger, CompleteCatalogue.RESOURCE_CREATED)

        record = handler.records[0]
        assert record.module == "emitters"
        assert record.lineno == expected_line

    def test_an_application_wrapper_can_point_past_itself(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        expected_line = emitters.emit_via_app_wrapper(logger, CompleteCatalogue.RESOURCE_CREATED)

        record = handler.records[0]
        assert record.module == "emitters"
        assert record.lineno == expected_line

    def test_never_reports_the_libraries_own_module(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        emitters.emit_directly(logger, CompleteCatalogue.RESOURCE_CREATED)

        assert handler.records[0].module != "events"


class TestCatalogueValidation:
    def test_a_complete_catalogue_has_no_missing_events(self) -> None:
        assert missing_events(CompleteCatalogue) == ()

    def test_reports_every_unfilled_slot(self) -> None:
        assert missing_events(IncompleteCatalogue) == (
            "SYS_UNHANDLED_EXCEPTION",
            "SYS_MISSING_CORRELATION_ID",
        )

    def test_validate_accepts_a_complete_catalogue(self) -> None:
        validate_catalogue(CompleteCatalogue)

    def test_validate_names_the_missing_slots(self) -> None:
        with pytest.raises(ValueError, match="SYS_UNHANDLED_EXCEPTION, SYS_MISSING_CORRELATION_ID"):
            validate_catalogue(IncompleteCatalogue)

    def test_the_bare_base_class_is_missing_everything(self) -> None:
        assert missing_events(EventCatalogue) == REQUIRED_EVENTS

    def test_a_slot_may_alias_another_event(self) -> None:
        """Some systems have no dedicated id for a trigger and reuse another."""

        class Aliasing(CompleteCatalogue):
            SYS_APP_CRASHED = CompleteCatalogue.SYS_APP_STOPPED

        assert missing_events(Aliasing) == ()
        assert Aliasing.SYS_APP_CRASHED.event_id == "100602"


class TestReservedFieldNames:
    """The standard library refuses to overwrite its own LogRecord attributes.

    Without this check the failure is a ``KeyError`` at log time, in whichever
    branch happens to run first in production.
    """

    def test_a_catalogue_using_ordinary_names_is_clean(self) -> None:
        assert reserved_field_names(CompleteCatalogue) == ()

    def test_names_the_event_and_the_field(self) -> None:
        class Clashing(CompleteCatalogue):
            SUBJECT_SEEN = LogEvent("100800", logging.INFO, (LoggingStreams.APP,), {LoggingStreams.APP: ("name",)})

        assert reserved_field_names(Clashing) == ("SUBJECT_SEEN.name",)

    def test_validate_rejects_the_catalogue_at_boot(self) -> None:
        class Clashing(CompleteCatalogue):
            SUBJECT_SEEN = LogEvent("100800", logging.INFO, (LoggingStreams.APP,), {LoggingStreams.APP: ("module",)})

        with pytest.raises(ValueError, match="SUBJECT_SEEN.module"):
            validate_catalogue(Clashing)

    def test_the_reserved_set_covers_what_the_standard_library_guards(self) -> None:
        assert {"name", "module", "filename", "lineno", "levelname", "args", "message"} <= RESERVED_FIELDS

    def test_the_reserved_set_covers_the_libraries_own_record_keys(self) -> None:
        assert {"event_id", "stream", "field_streams"} <= RESERVED_FIELDS

    def test_a_reserved_field_really_does_break_the_standard_library(self, logger: logging.Logger) -> None:
        """The check is worth having only if the failure it prevents is real."""
        with pytest.raises(KeyError, match="module"):
            emit(logger, CompleteCatalogue.ACCESS_REQUEST, "access", module="auth")

    def test_the_running_interpreter_adds_no_attribute_the_frozen_set_misses(self) -> None:
        """The guard on the frozen list.

        A Python release that adds a ``LogRecord`` attribute would slip past a
        set spelled out by hand. The matrix runs this on every supported
        interpreter, so it surfaces here instead of as a ``KeyError`` later.
        """
        record = logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None)

        assert frozenset(record.__dict__) <= _STDLIB_RECORD_FIELDS

    def test_the_frozen_set_covers_interpreters_the_running_one_is_older_than(self) -> None:
        """``taskName`` arrived in 3.12 and is the reason the set is frozen."""
        assert "taskName" in _STDLIB_RECORD_FIELDS


class TestDefaultEventCatalogue:
    def test_fills_every_required_slot(self) -> None:
        assert missing_events(DefaultEventCatalogue) == ()

    def test_passes_validation_unchanged(self) -> None:
        validate_catalogue(DefaultEventCatalogue)

    def test_an_application_overrides_only_what_differs(self) -> None:
        class Log(DefaultEventCatalogue):
            SYS_APP_STARTED = LogEvent("900001", logging.INFO, (LoggingStreams.APP,))

        assert Log.SYS_APP_STARTED.event_id == "900001"
        assert Log.ACCESS_REQUEST.event_id == DefaultEventCatalogue.ACCESS_REQUEST.event_id
        assert missing_events(Log) == ()

    def test_siem_is_allow_listed_on_every_event_that_reaches_it(self) -> None:
        for name, event in ((n, e) for n, e in vars(DefaultEventCatalogue).items() if isinstance(e, LogEvent)):
            if LoggingStreams.SIEM in event.streams:
                assert event.fields.get(LoggingStreams.SIEM) is not None, name


class TestStrictFields:
    @pytest.fixture(autouse=True)
    def strict(self) -> Any:
        set_strict_fields(True)
        yield
        set_strict_fields(False)

    def test_rejects_a_field_no_stream_would_carry(self, logger: logging.Logger) -> None:
        with pytest.raises(ValueError, match="resouce_id"):
            emit(logger, CompleteCatalogue.RESOURCE_CREATED, "created", resouce_id="r-1")

    def test_accepts_an_allow_listed_field(self, logger: logging.Logger, handler: RecordingHandler) -> None:
        emit(logger, CompleteCatalogue.RESOURCE_CREATED, "created", resource_id="r-1")

        assert handler.records[0].resource_id == "r-1"  # type: ignore[attr-defined]

    def test_accepts_correlation_metadata_that_every_stream_keeps(
        self, logger: logging.Logger, handler: RecordingHandler
    ) -> None:
        emit(logger, CompleteCatalogue.RESOURCE_CREATED, "created", request_id="req-1")

        assert handler.records[0].request_id == "req-1"  # type: ignore[attr-defined]

    def test_says_nothing_about_an_event_that_declares_no_routing(self, logger: logging.Logger) -> None:
        emit(logger, LogEvent("1", logging.INFO, (LoggingStreams.APP,)), "no routing", anything="goes")

    def test_is_off_by_default_so_a_typo_never_takes_a_request_down(self, logger: logging.Logger) -> None:
        set_strict_fields(False)

        emit(logger, CompleteCatalogue.RESOURCE_CREATED, "created", resouce_id="r-1")

    def test_reports_which_fields_reach_nothing(self) -> None:
        assert unrouted_fields(CompleteCatalogue.RESOURCE_CREATED, iter(["resource_id", "nope"])) == ("nope",)


class TestAccessEventId:
    def test_maps_a_route_to_its_own_event_id(self) -> None:
        assert CompleteCatalogue.access_event_id[("POST", "/resources")] == "100700"

    def test_defaults_to_empty_when_an_application_declares_none(self) -> None:
        class NoRoutes(EventCatalogue):
            pass

        assert NoRoutes.access_event_id == {}
