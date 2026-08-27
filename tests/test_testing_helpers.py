import logging

import pytest

from gfmodules.logging.events import DefaultEventCatalogue, emit
from gfmodules.logging.streams import LoggingStreams
from gfmodules.logging.testing import (
    assert_catalogue_complete,
    assert_event_emitted,
    assert_fields_absent,
    capture_records,
    capture_stream,
)
from tests.helpers.catalogue import CompleteCatalogue, IncompleteCatalogue

logger = logging.getLogger("app.health")
CREATED = CompleteCatalogue.RESOURCE_CREATED


@pytest.fixture(autouse=True)
def propagating_logger() -> None:
    logger.handlers = []
    logger.propagate = True
    logger.setLevel(logging.DEBUG)


class TestCaptureRecords:
    def test_captures_what_was_logged(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "resource created", fields={"resource_id": "12345"})

        assert len(captured) == 1
        assert captured.entries[0].event_id == "100607"
        assert captured.entries[0].description == "resource created"
        assert captured.entries[0].level == "INFO"

    def test_renders_the_message_the_log_server_would_receive(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "resource created", fields={"resource_id": "12345", "owner_id": "o-1"})

        assert captured.entries[0].message == {"resource_id": "12345", "owner_id": "o-1"}

    def test_stops_capturing_after_the_block(self) -> None:
        with capture_records() as captured:
            pass
        emit(logger, CREATED, "resource created")

        assert len(captured) == 0

    def test_restores_the_previous_handlers(self) -> None:
        root = logging.getLogger()
        before = list(root.handlers)

        with capture_records():
            pass

        assert root.handlers == before

    def test_can_target_a_named_logger(self) -> None:
        isolated = logging.getLogger("tests.isolated")
        isolated.propagate = False

        with capture_records("tests.isolated") as captured:
            emit(isolated, CREATED, "resource created")

        assert len(captured) == 1

    def test_selects_records_by_event(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "created")
            emit(logger, CompleteCatalogue.SYS_APP_STARTED, "started")

        assert len(captured.for_event(CREATED)) == 1

    def test_selects_records_by_stream_using_the_real_filters(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "created")
            emit(logger, CompleteCatalogue.SYS_APP_STARTED, "started")  # app stream only

        assert len(captured.for_stream(LoggingStreams.APP)) == 2
        assert len(captured.for_stream(LoggingStreams.SIEM)) == 1


class TestCaptureStream:
    def test_applies_the_per_event_field_allow_list(self) -> None:
        with capture_stream(LoggingStreams.SIEM) as siem:
            emit(logger, CREATED, "created", fields={"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"})

        assert siem == [{"resource_id": "12345"}]

    def test_the_app_stream_sees_its_own_allow_list(self) -> None:
        with capture_stream(LoggingStreams.APP) as app:
            emit(logger, CREATED, "created", fields={"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"})

        assert app == [{"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"}]

    def test_excludes_records_the_stream_filter_rejects(self) -> None:
        with capture_stream(LoggingStreams.SIEM) as siem:
            emit(logger, CompleteCatalogue.SYS_APP_STARTED, "started")

        assert siem == []

    def test_restores_the_previous_handlers(self) -> None:
        root = logging.getLogger()
        before = list(root.handlers)

        with capture_stream(LoggingStreams.SIEM):
            pass

        assert root.handlers == before


class TestNestedCaptures:
    """Per-stream routing is a security boundary, so the helpers have to observe
    one record arriving at several streams at once.
    """

    def test_two_streams_observe_the_same_record(self) -> None:
        with capture_stream(LoggingStreams.APP) as app, capture_stream(LoggingStreams.SIEM) as siem:
            emit(logger, CREATED, "created", fields={"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"})

        assert app == [{"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"}]
        assert siem == [{"resource_id": "12345"}]

    def test_a_field_can_be_shown_absent_from_one_stream_only(self) -> None:
        with capture_stream(LoggingStreams.APP) as app, capture_stream(LoggingStreams.SIEM) as siem:
            emit(logger, CREATED, "created", fields={"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"})

        assert_fields_absent(siem, "owner_id", "created_by")
        assert app[0]["owner_id"] == "o-1"

    def test_record_and_stream_captures_nest_together(self) -> None:
        with capture_records() as captured, capture_stream(LoggingStreams.SIEM) as siem:
            emit(logger, CREATED, "created", fields={"resource_id": "12345", "owner_id": "o-1"})

        assert len(captured) == 1
        assert siem == [{"resource_id": "12345"}]

    def test_the_inner_capture_stops_at_its_own_block(self) -> None:
        with capture_stream(LoggingStreams.APP) as app:
            with capture_stream(LoggingStreams.SIEM) as siem:
                emit(logger, CREATED, "created", fields={"resource_id": "1"})
            emit(logger, CREATED, "created", fields={"resource_id": "2"})

        assert [message["resource_id"] for message in app] == ["1", "2"]
        assert [message["resource_id"] for message in siem] == ["1"]

    def test_captures_still_detach_the_real_handlers(self) -> None:
        """Nesting keeps other captures attached, not the application's own."""
        root = logging.getLogger()
        real = logging.Handler()
        root.handlers = [real]

        try:
            with capture_stream(LoggingStreams.APP), capture_stream(LoggingStreams.SIEM):
                assert real not in root.handlers
        finally:
            root.handlers = []


class TestAssertEventEmitted:
    def test_returns_the_matching_record(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "created", fields={"resource_id": "12345"})

        entry = assert_event_emitted(captured, CREATED, resource_id="12345")

        assert entry.description == "created"

    def test_fails_when_the_event_was_never_emitted(self) -> None:
        with capture_records() as captured:
            pass

        with pytest.raises(AssertionError, match="no record emitted with event id 100607"):
            assert_event_emitted(captured, CREATED)

    def test_fails_when_no_record_carries_the_expected_fields(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "created", fields={"resource_id": "99999"})

        with pytest.raises(AssertionError, match="none carried"):
            assert_event_emitted(captured, CREATED, resource_id="12345")

    def test_matches_the_right_record_among_several(self) -> None:
        with capture_records() as captured:
            emit(logger, CREATED, "first", fields={"resource_id": "11111"})
            emit(logger, CREATED, "second", fields={"resource_id": "22222"})

        assert assert_event_emitted(captured, CREATED, resource_id="22222").description == "second"


class TestAssertCatalogueComplete:
    def test_accepts_a_complete_catalogue(self) -> None:
        assert_catalogue_complete(CompleteCatalogue)

    def test_names_the_missing_events(self) -> None:
        with pytest.raises(AssertionError, match="SYS_UNHANDLED_EXCEPTION"):
            assert_catalogue_complete(IncompleteCatalogue)

    def test_names_the_slots_inheriting_routing_without_an_id(self) -> None:
        with pytest.raises(AssertionError, match="SYS_APP_STARTED"):
            assert_catalogue_complete(DefaultEventCatalogue)


class TestAssertFieldsAbsent:
    def test_passes_when_nothing_leaked(self) -> None:
        assert_fields_absent([{"resource_id": "1"}], "owner_id", "created_by")

    def test_fails_naming_the_leaked_field(self) -> None:
        with pytest.raises(AssertionError, match=r"\['owner_id'\]"):
            assert_fields_absent([{"resource_id": "1", "owner_id": "o-1"}], "owner_id")
