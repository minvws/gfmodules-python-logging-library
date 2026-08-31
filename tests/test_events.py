import logging
from typing import Any

import pytest

from gfmodules.logging.events import (
    _STDLIB_RECORD_FIELDS,
    REQUIRED_EVENTS,
    RESERVED_FIELDS,
    UNSET_EVENT_ID,
    DefaultEventCatalogue,
    EventCatalogue,
    LogEvent,
    declared_events,
    emit,
    missing_events,
    reserved_field_names,
    set_strict_fields,
    unrouted_fields,
    unset_event_ids,
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


class SystemIdsFilled(DefaultEventCatalogue):
    SYS_APP_STARTED = DefaultEventCatalogue.SYS_APP_STARTED.with_id("100801")
    SYS_APP_STOPPED = DefaultEventCatalogue.SYS_APP_STOPPED.with_id("100802")
    SYS_APP_CRASHED = DefaultEventCatalogue.SYS_APP_CRASHED.with_id("100803")
    SYS_UNHANDLED_EXCEPTION = DefaultEventCatalogue.SYS_UNHANDLED_EXCEPTION.with_id("100804")
    SYS_MISSING_CORRELATION_ID = DefaultEventCatalogue.SYS_MISSING_CORRELATION_ID.with_id("100806")
    ACCESS_REQUEST = DefaultEventCatalogue.ACCESS_REQUEST.with_id("094500")


class TestLogEventCopies:
    def test_with_id_keeps_everything_else(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED.with_id("100801")

        assert event.event_id == "100801"
        assert event.level == DefaultEventCatalogue.SYS_APP_STARTED.level
        assert event.streams == DefaultEventCatalogue.SYS_APP_STARTED.streams
        assert event.fields == DefaultEventCatalogue.SYS_APP_STARTED.fields

    def test_the_original_is_left_alone(self) -> None:
        DefaultEventCatalogue.SYS_APP_STARTED.with_id("100801")

        assert DefaultEventCatalogue.SYS_APP_STARTED.event_id == UNSET_EVENT_ID

    def test_replace_changes_every_attribute_at_once(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STOPPED.replace(
            event_id="100802",
            level=logging.WARNING,
            streams=(LoggingStreams.APP,),
            fields={LoggingStreams.APP: ("shutdown_reason",)},
        )

        assert event.event_id == "100802"
        assert event.level == logging.WARNING
        assert event.streams == (LoggingStreams.APP,)
        assert event.fields == {LoggingStreams.APP: ("shutdown_reason",)}

    def test_replace_leaves_out_what_it_is_not_given(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STOPPED.replace(level=logging.WARNING)

        assert event.level == logging.WARNING
        assert event.streams == DefaultEventCatalogue.SYS_APP_STOPPED.streams
        assert event.fields == DefaultEventCatalogue.SYS_APP_STOPPED.fields

    def test_empty_fields_clears_the_routing_rather_than_meaning_unset(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STOPPED.replace(fields={})

        assert event.fields == {}


class TestAddFields:
    def test_merges_into_a_stream_the_event_already_routes(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={LoggingStreams.APP: ("region",)})

        assert event.fields[LoggingStreams.APP] == ("version", "config_path", "region")

    def test_the_declared_order_survives_a_merge(self) -> None:
        inherited = DefaultEventCatalogue.SYS_APP_STARTED.fields[LoggingStreams.APP]

        event = DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={LoggingStreams.APP: ("region",)})

        assert event.fields[LoggingStreams.APP][: len(inherited)] == inherited

    def test_adds_a_stream_the_event_did_not_route(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={LoggingStreams.SIEM: ("version",)})

        assert event.fields[LoggingStreams.SIEM] == ("version",)
        assert event.fields[LoggingStreams.APP] == ("version", "config_path")

    def test_names_the_allow_list_already_has_are_not_repeated(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={LoggingStreams.APP: ("version", "region")})

        assert event.fields[LoggingStreams.APP] == ("version", "config_path", "region")

    def test_leaves_the_streams_it_was_not_given_alone(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STOPPED.add_fields(fields={LoggingStreams.APP: ("uptime_seconds",)})

        assert event.fields[LoggingStreams.SIEM] == DefaultEventCatalogue.SYS_APP_STOPPED.fields[LoggingStreams.SIEM]

    def test_keeps_the_id_level_and_streams(self) -> None:
        base = DefaultEventCatalogue.SYS_APP_STOPPED.with_id("100802")

        event = base.add_fields(fields={LoggingStreams.APP: ("uptime_seconds",)})

        assert event.event_id == "100802"
        assert event.level == base.level
        assert event.streams == base.streams

    def test_the_original_is_left_alone(self) -> None:
        DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={LoggingStreams.APP: ("region",)})

        assert DefaultEventCatalogue.SYS_APP_STARTED.fields[LoggingStreams.APP] == ("version", "config_path")

    def test_nothing_to_add_is_the_event_itself(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED

        assert event.add_fields() is event
        assert event.add_fields(fields=None) is event

    def test_an_empty_mapping_changes_no_routing(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={})

        assert event.fields == DefaultEventCatalogue.SYS_APP_STARTED.fields

    def test_a_stream_is_allow_listed_without_being_routed_to(self) -> None:
        event = DefaultEventCatalogue.SYS_APP_STARTED.add_fields(fields={LoggingStreams.SIEM: ("version",)})

        assert LoggingStreams.SIEM in event.fields
        assert LoggingStreams.SIEM not in event.streams

    def test_an_event_that_routed_everything_now_routes_an_allow_list(self) -> None:
        unrouted = LogEvent("100610", logging.INFO, (LoggingStreams.APP,))

        event = unrouted.add_fields(fields={LoggingStreams.APP: ("resource_id",)})

        assert unrouted_fields(unrouted, ["owner_id"]) == ()
        assert unrouted_fields(event, ["owner_id"]) == ("owner_id",)


class TestUnsetEventIds:
    def test_the_default_catalogue_supplies_no_ids(self) -> None:
        assert unset_event_ids(DefaultEventCatalogue) == tuple(sorted(REQUIRED_EVENTS))

    def test_validate_rejects_a_catalogue_that_leaves_one_unfilled(self) -> None:
        class Log(DefaultEventCatalogue):
            SYS_APP_STARTED = DefaultEventCatalogue.SYS_APP_STARTED.with_id("100801")

        with pytest.raises(ValueError, match="ACCESS_REQUEST"):
            validate_catalogue(Log)

    def test_the_error_points_at_the_way_out(self) -> None:
        with pytest.raises(ValueError, match="declares events with no event id"):
            validate_catalogue(DefaultEventCatalogue)

    def test_an_unfilled_id_on_an_applications_own_event_is_caught_too(self) -> None:
        class Log(SystemIdsFilled):
            RESOURCE_CREATED = LogEvent(UNSET_EVENT_ID, logging.INFO, (LoggingStreams.APP,))

        assert unset_event_ids(Log) == ("RESOURCE_CREATED",)

    def test_a_catalogue_with_every_id_filled_passes(self) -> None:
        validate_catalogue(SystemIdsFilled)


class TestDefaultEventCatalogue:
    def test_fills_every_required_slot(self) -> None:
        assert missing_events(DefaultEventCatalogue) == ()

    def test_an_application_overrides_only_what_differs(self) -> None:
        class Log(SystemIdsFilled):
            SYS_APP_STARTED = LogEvent("900001", logging.INFO, (LoggingStreams.APP,))

        assert Log.SYS_APP_STARTED.event_id == "900001"
        assert Log.SYS_APP_STARTED.fields == {}
        assert Log.ACCESS_REQUEST.fields == DefaultEventCatalogue.ACCESS_REQUEST.fields
        assert missing_events(Log) == ()

    def test_declares_only_the_events_the_library_emits(self) -> None:
        assert {name for name, _ in declared_events(DefaultEventCatalogue)} == set(REQUIRED_EVENTS)

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
