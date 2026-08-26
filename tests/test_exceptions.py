"""Tests for the exception-handler primitives.

The library never registers a handler itself, so each test wires one the way an
application would and uses the primitive for the logging half.
"""

import logging

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from gfmodules.logging.context import CORRELATION_ID_HEADER, REQUEST_ID_HEADER
from gfmodules.logging.exceptions import log_unhandled_exception
from gfmodules.logging.middleware import RequestContextMiddleware, restore_request_context
from tests.conftest import RecordingHandler
from tests.helpers.catalogue import CompleteCatalogue

UNHANDLED = CompleteCatalogue.SYS_UNHANDLED_EXCEPTION.event_id

logger = logging.getLogger("tests.exceptions")


def build_client(*, with_middleware: bool = True, decorated: bool = True) -> TestClient:
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> Response:
        raise ValueError("boom")

    async def handler(request: Request, exc: Exception) -> Response:
        log_unhandled_exception(logger, request, exc)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    app.add_exception_handler(Exception, restore_request_context(handler) if decorated else handler)
    if with_middleware:
        app.add_middleware(RequestContextMiddleware)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def propagating_logger(records: RecordingHandler) -> None:
    logger.handlers = []
    logger.propagate = True
    logger.setLevel(logging.DEBUG)


class TestLogUnhandledException:
    def test_logs_the_exception_with_its_type_and_route(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        build_client().get("/boom")

        record = records.with_event_id(UNHANDLED)[0]
        assert record.exception_type == "ValueError"  # type: ignore[attr-defined]
        assert record.endpoint == "/boom"  # type: ignore[attr-defined]
        assert record.method == "GET"  # type: ignore[attr-defined]

    def test_carries_the_traceback(self, catalogue: type[CompleteCatalogue], records: RecordingHandler) -> None:
        build_client().get("/boom")

        assert records.with_event_id(UNHANDLED)[0].exc_info is not None

    def test_rebinds_the_request_context_that_the_middleware_tore_down(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        response = build_client().get("/boom", headers={CORRELATION_ID_HEADER: "corr-1"})

        message = records.messages_with_event_id(UNHANDLED)[0]
        assert message["correlation_id"] == "corr-1"
        assert message["request_id"] == response.headers[REQUEST_ID_HEADER]

    def test_logs_the_context_even_when_the_handler_is_not_decorated(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        # An undecorated handler still logs with the context, because the
        # primitive rebinds it; it just answers without the correlation headers.
        response = build_client(decorated=False).get("/boom", headers={CORRELATION_ID_HEADER: "corr-1"})

        assert CORRELATION_ID_HEADER not in response.headers
        assert records.messages_with_event_id(UNHANDLED)[0]["correlation_id"] == "corr-1"

    def test_still_logs_when_the_request_never_reached_the_middleware(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        response = build_client(with_middleware=False).get("/boom")

        assert response.status_code == 500
        assert REQUEST_ID_HEADER not in response.headers
        message = records.messages_with_event_id(UNHANDLED)[0]
        assert message["exception_type"] == "ValueError"
        assert "request_id" not in message

    def test_the_application_keeps_control_of_the_response_body(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        assert build_client().get("/boom").json() == {"error": "Internal server error"}
