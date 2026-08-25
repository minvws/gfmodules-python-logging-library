"""The tests an application should have about its own logging."""

from typing import Any

from starlette.testclient import TestClient

import gfmodules.logging as gflog
from fastapi_app.app import create_app
from fastapi_app.events import Log
from gfmodules.logging import LoggingStreams
from gfmodules.logging.testing import (
    assert_catalogue_complete,
    assert_event_emitted,
    assert_fields_absent,
    capture_records,
    capture_stream,
)

RESOURCE: dict[str, Any] = {"resource_id": "r-1", "owner_id": "o-1", "created_by": "u-1"}


class TestCatalogue:
    def test_every_required_event_is_defined(self) -> None:
        """A missing slot is invisible to a type checker, so it is caught here."""
        assert_catalogue_complete(Log)


class TestRequestContext:
    def test_a_domain_event_carries_the_context_no_one_passed_it(self) -> None:
        with capture_records() as captured:
            with TestClient(create_app()) as client:
                response = client.post(
                    "/resources",
                    json=RESOURCE,
                    headers={gflog.CORRELATION_ID_HEADER: "corr-1", "X-Tenant-Id": "t-1"},
                )

        entry = assert_event_emitted(captured, Log.RESOURCE_CREATED, resource_id="r-1")
        assert entry.message["correlation_id"] == "corr-1"
        assert entry.message["endpoint"] == "/resources"
        assert entry.message["tenant_id"] == "t-1"
        assert entry.message["request_id"] == response.headers[gflog.REQUEST_ID_HEADER]

    def test_a_route_with_its_own_access_event_id_uses_it(self) -> None:
        with capture_records() as captured:
            with TestClient(create_app()) as client:
                client.post("/resources", json=RESOURCE)

        assert [entry for entry in captured if entry.event_id == "100710"]


class TestStreamSeparation:
    def test_siem_sees_the_resource_id_and_nothing_else(self) -> None:
        with capture_stream(LoggingStreams.SIEM) as siem:
            with TestClient(create_app()) as client:
                client.post("/resources", json=RESOURCE)

        assert_fields_absent(siem, "owner_id", "created_by")
        assert any(message.get("resource_id") == "r-1" for message in siem)

    def test_the_app_stream_keeps_the_detail_siem_is_denied(self) -> None:
        with capture_stream(LoggingStreams.APP) as app_stream:
            with TestClient(create_app()) as client:
                client.post("/resources", json=RESOURCE)

        created = [message for message in app_stream if message.get("resource_id")]
        assert created[0]["owner_id"] == "o-1"
        assert created[0]["created_by"] == "u-1"


class TestFailures:
    def test_a_rejected_lookup_reports_the_calling_line_not_the_helper(self) -> None:
        with capture_records() as captured:
            with TestClient(create_app()) as client:
                client.delete("/resources/missing")

        entry = assert_event_emitted(captured, Log.LOOKUP_REJECTED, error_reason="unknown resource_id")
        assert entry.payload["source"].startswith("service:")

    def test_an_unhandled_exception_is_logged_with_its_request(self) -> None:
        with capture_records() as captured:
            with TestClient(create_app(), raise_server_exceptions=False) as client:
                response = client.get("/boom", headers={gflog.CORRELATION_ID_HEADER: "corr-1"})

        assert response.status_code == 500
        entry = assert_event_emitted(captured, Log.SYS_UNHANDLED_EXCEPTION, exception_type="RuntimeError")
        assert entry.message["endpoint"] == "/boom"
        assert entry.message["correlation_id"] == "corr-1"
        assert response.headers[gflog.CORRELATION_ID_HEADER] == "corr-1"


class TestApplicationLifecycle:
    def test_started_and_stopped_bracket_the_application(self) -> None:
        with capture_records() as captured:
            with TestClient(create_app()):
                pass

        assert_event_emitted(captured, Log.SYS_APP_STARTED, version="1.4.0")
        assert_event_emitted(captured, Log.SYS_APP_STOPPED, shutdown_reason="graceful")
