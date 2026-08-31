"""End-to-end test of a FastAPI application wired up the way an app would be.

Deliberately limited to the library's public API, so what it exercises is the
surface applications actually consume.
"""

import json
import logging
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

import gfmodules.logging as gflog
from gfmodules.logging.exceptions import log_unhandled_exception
from gfmodules.logging.middleware import RequestContextMiddleware, restore_request_context
from gfmodules.logging.streams import LoggingStreams
from gfmodules.logging.testing import assert_event_emitted, assert_fields_absent, capture_records, capture_stream
from tests.helpers.catalogue import CompleteCatalogue, IncompleteCatalogue

TENANT_ID = gflog.ContextField(name="tenant_id", header="X-Tenant-Id")

logger = logging.getLogger("app.service")


def build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with gflog.lifespan_logging(logger, version="1.2.3", config_path="/etc/app.conf"):
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/resources")
    async def list_resources() -> Response:
        gflog.emit(
            logger,
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "12345", "owner_id": "o-1", "created_by": "alice"},
        )
        return JSONResponse({"resources": []})

    @app.delete("/resources/{id}")
    async def delete_resource(id: str) -> Response:
        return JSONResponse({"deleted": id})

    @app.get("/boom")
    async def boom() -> Response:
        raise ValueError("boom")

    @restore_request_context
    async def unhandled(request: Request, exc: Exception) -> Response:
        log_unhandled_exception(logger, request, exc)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    app.add_exception_handler(Exception, unhandled)
    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.fixture(autouse=True)
def configured() -> Iterator[None]:
    gflog.configure(
        config=gflog.ConfigLogging(application_id="example-service", debug_logs_in_console=False, access_logs=True),
        loglevel="info",
        catalogue=CompleteCatalogue,
        extra_context_fields=(TENANT_ID,),
    )
    logger.handlers = []
    logger.propagate = True
    logger.setLevel(logging.DEBUG)
    yield
    logging.getLogger().handlers = []


class TestRequestLifecycle:
    def test_an_event_logged_in_a_handler_carries_the_request_context(self) -> None:
        with capture_records() as captured:
            with TestClient(build_app()) as client:
                response = client.get(
                    "/resources",
                    headers={gflog.CORRELATION_ID_HEADER: "corr-1", "X-Tenant-Id": "t-1"},
                )

        entry = assert_event_emitted(captured, CompleteCatalogue.RESOURCE_CREATED, resource_id="12345")
        assert entry.message["correlation_id"] == "corr-1"
        assert entry.message["endpoint"] == "/resources"
        assert entry.message["method"] == "GET"
        assert entry.message["request_id"] == response.headers[gflog.REQUEST_ID_HEADER]

    def test_a_declared_extra_context_field_reaches_the_record(self) -> None:
        with capture_records() as captured:
            with TestClient(build_app()) as client:
                client.get("/resources", headers={"X-Tenant-Id": "t-1"})

        entry = assert_event_emitted(captured, CompleteCatalogue.RESOURCE_CREATED)
        assert entry.message["tenant_id"] == "t-1"

    def test_the_access_record_reports_the_outcome(self) -> None:
        with capture_records() as captured:
            with TestClient(build_app()) as client:
                client.get("/resources")

        assert_event_emitted(captured, CompleteCatalogue.ACCESS_REQUEST, status_code=200)

    def test_a_route_with_its_own_event_id_uses_it(self) -> None:
        with capture_records() as captured:
            with TestClient(build_app()) as client:
                client.delete("/resources/7")

        assert [entry for entry in captured if entry.event_id == "100702"]

    def test_no_access_record_is_logged_unless_the_configuration_enables_it(self) -> None:
        gflog.configure(
            config=gflog.ConfigLogging(application_id="example-service"),
            loglevel="info",
            catalogue=CompleteCatalogue,
            extra_context_fields=(TENANT_ID,),
        )

        with capture_records() as captured:
            with TestClient(build_app()) as client:
                client.get("/resources")

        assert captured.for_event(CompleteCatalogue.ACCESS_REQUEST) == []
        assert_event_emitted(captured, CompleteCatalogue.RESOURCE_CREATED)


class TestStreamSeparation:
    def test_the_siem_stream_only_receives_its_allow_listed_fields(self) -> None:
        with capture_stream(LoggingStreams.SIEM) as siem:
            with TestClient(build_app()) as client:
                client.get("/resources")

        assert_fields_absent(siem, "owner_id", "created_by", "config_path", "version")
        assert any(message.get("resource_id") == "12345" for message in siem)

    def test_the_app_stream_receives_the_wider_set(self) -> None:
        with capture_stream(LoggingStreams.APP) as app_stream:
            with TestClient(build_app()) as client:
                client.get("/resources")

        created = [message for message in app_stream if message.get("resource_id")]
        assert created[0]["owner_id"] == "o-1"
        assert created[0]["created_by"] == "alice"


class TestApplicationLifecycle:
    def test_started_and_stopped_bracket_the_application(self) -> None:
        with capture_records() as captured:
            with TestClient(build_app()):
                pass

        assert_event_emitted(captured, CompleteCatalogue.SYS_APP_STARTED, version="1.2.3")
        stopped = [
            entry
            for entry in captured.for_event(CompleteCatalogue.SYS_APP_STOPPED)
            if entry.level == "INFO" and "shutdown_reason" in entry.message
        ]
        assert stopped[0].message["shutdown_reason"] == "graceful"


class TestUnhandledExceptions:
    def test_the_exception_is_logged_with_the_request_context(self) -> None:
        with capture_records() as captured:
            with TestClient(build_app(), raise_server_exceptions=False) as client:
                response = client.get("/boom", headers={gflog.CORRELATION_ID_HEADER: "corr-1"})

        assert response.status_code == 500
        entry = assert_event_emitted(captured, CompleteCatalogue.SYS_UNHANDLED_EXCEPTION, exception_type="ValueError")
        assert entry.message["endpoint"] == "/boom"
        assert entry.message["correlation_id"] == "corr-1"
        assert entry.message["exception"].startswith("Traceback (most recent call last):")

    def test_the_correlation_headers_are_echoed_on_the_error_response(self) -> None:
        with TestClient(build_app(), raise_server_exceptions=False) as client:
            response = client.get("/boom", headers={gflog.CORRELATION_ID_HEADER: "corr-1"})

        assert response.headers[gflog.CORRELATION_ID_HEADER] == "corr-1"
        assert response.headers[gflog.REQUEST_ID_HEADER]


class TestConfigure:
    def test_rejects_an_unknown_log_level(self) -> None:
        config = gflog.ConfigLogging()

        with pytest.raises(ValueError, match="invalid loglevel SHOUT"):
            gflog.configure(config=config, loglevel="shout", catalogue=CompleteCatalogue)

    def test_rejects_a_catalogue_missing_required_events(self) -> None:
        config = gflog.ConfigLogging()

        with pytest.raises(ValueError, match="does not define required events"):
            gflog.configure(config=config, loglevel="INFO", catalogue=IncompleteCatalogue)

    def test_installs_handlers_that_emit_the_agreed_json_shape(self) -> None:
        stream = logging.getLogger().handlers[0].stream  # type: ignore[attr-defined]
        assert stream is not None

        record = logging.LogRecord("app.x", logging.INFO, "", 1, "hello", (), None)
        record.event_id = "100601"
        payload = json.loads(logging.getLogger().handlers[0].format(record))

        assert payload["application_id"] == "example-service"
        assert set(payload) >= {"event_id", "timestamp", "level", "event_description", "source", "message"}
