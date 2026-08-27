"""Middleware tests.

These build FastAPI applications rather than bare Starlette ones because
per-route access event ids depend on ``scope["route"]``, which FastAPI's
``APIRoute`` sets and a plain Starlette ``Route`` does not.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from gfmodules.logging.context import (
    CLIENT_TRACE_ID_HEADER,
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    UNSET,
    ContextField,
    collect_context,
    register_context_fields,
)
from gfmodules.logging.middleware import (
    RequestContext,
    RequestContextMiddleware,
    _read_body,
    bind_request_context,
    restore_request_context,
)
from tests.conftest import RecordingHandler
from tests.helpers.catalogue import CompleteCatalogue

ACCESS_EVENT_ID = CompleteCatalogue.ACCESS_REQUEST.event_id
MISSING_CORRELATION_EVENT_ID = CompleteCatalogue.SYS_MISSING_CORRELATION_ID.event_id


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ok")
    @app.post("/ok")
    async def ok() -> Response:
        return JSONResponse({"ok": True})

    @app.get("/context")
    async def context() -> Response:
        return JSONResponse(collect_context())

    @app.post("/echo")
    async def echo(request: Request) -> Response:
        return JSONResponse({"body": (await request.body()).decode()})

    @app.post("/stream")
    async def stream(request: Request) -> Response:
        chunks = [chunk async for chunk in request.stream()]
        return JSONResponse({"body": b"".join(chunks).decode()})

    @app.get("/boom")
    async def boom() -> Response:
        raise ValueError("boom")

    @app.delete("/resources/{id}")
    async def delete_resource(id: str) -> Response:
        return JSONResponse({"deleted": id})

    return app


def build_client(**options: Any) -> TestClient:
    app = build_app()
    app.add_middleware(RequestContextMiddleware, **options)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(catalogue: type[CompleteCatalogue]) -> TestClient:
    return build_client()


class TestContextBinding:
    def test_binds_the_request_details_for_the_handler(self, client: TestClient) -> None:
        body = client.get("/context").json()

        assert body["endpoint"] == "/context"
        assert body["method"] == "GET"
        assert body["request_id"]
        assert body["ip"]

    def test_binds_the_declared_correlation_headers(self, client: TestClient) -> None:
        body = client.get(
            "/context",
            headers={CORRELATION_ID_HEADER: "corr-1", CLIENT_TRACE_ID_HEADER: "trace-1"},
        ).json()

        assert body["correlation_id"] == "corr-1"
        assert body["client_trace_id"] == "trace-1"

    def test_omits_correlation_headers_that_were_not_sent(self, client: TestClient) -> None:
        assert "correlation_id" not in client.get("/context").json()

    def test_binds_the_user_agent_as_the_caller_sent_it(self, client: TestClient) -> None:
        body = client.get("/context", headers={"User-Agent": "kube-probe/1.31"}).json()

        assert body["user_agent"] == "kube-probe/1.31"

    def test_binds_application_declared_extra_fields(self, catalogue: type[CompleteCatalogue]) -> None:
        register_context_fields((ContextField(name="tenant_id", header="X-Tenant-Id"),))
        client = build_client()

        body = client.get("/context", headers={"X-Tenant-Id": "t-1"}).json()

        assert body["tenant_id"] == "t-1"

    def test_sanitizes_hostile_header_values(self, client: TestClient) -> None:
        body = client.get("/context", headers={CORRELATION_ID_HEADER: "../../etc/passwd"}).json()

        assert body["correlation_id"] == "etcpasswd"

    def test_the_context_does_not_leak_past_the_request(self, client: TestClient) -> None:
        client.get("/context")

        assert collect_context() == {}

    def test_each_request_gets_its_own_request_id(self, client: TestClient) -> None:
        first = client.get("/context").json()["request_id"]
        second = client.get("/context").json()["request_id"]

        assert first != second


class TestResponseHeaders:
    def test_echoes_the_request_id(self, client: TestClient) -> None:
        assert client.get("/ok").headers[REQUEST_ID_HEADER]

    def test_echoes_the_correlation_headers_that_were_sent(self, client: TestClient) -> None:
        response = client.get("/ok", headers={CORRELATION_ID_HEADER: "corr-1", CLIENT_TRACE_ID_HEADER: "trace-1"})

        assert response.headers[CORRELATION_ID_HEADER] == "corr-1"
        assert response.headers[CLIENT_TRACE_ID_HEADER] == "trace-1"

    def test_omits_correlation_headers_that_were_not_sent(self, client: TestClient) -> None:
        response = client.get("/ok")

        assert CORRELATION_ID_HEADER not in response.headers
        assert CLIENT_TRACE_ID_HEADER not in response.headers


class StampUpstreamId(BaseHTTPMiddleware):
    """Stands in for an upstream middleware that already assigned a request id."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state["id"] = "upstream-id"
        return await call_next(request)


class TestRequestId:
    def test_generates_a_fresh_id_by_default(self, catalogue: type[CompleteCatalogue]) -> None:
        client = build_client()

        first = client.get("/context").json()["request_id"]
        second = client.get("/context").json()["request_id"]

        assert first != second

    def test_ignores_an_upstream_id_unless_asked_to_reuse_it(self, catalogue: type[CompleteCatalogue]) -> None:
        app = build_app()
        app.add_middleware(RequestContextMiddleware)
        app.add_middleware(StampUpstreamId)

        assert TestClient(app).get("/context").json()["request_id"] != "upstream-id"

    def test_reuses_an_upstream_id_when_asked_to(self, catalogue: type[CompleteCatalogue]) -> None:
        app = build_app()
        app.add_middleware(RequestContextMiddleware, reuse_request_state_id=True)
        # Added last so it runs first and can stamp the id before we read it.
        app.add_middleware(StampUpstreamId)

        assert TestClient(app).get("/context").json()["request_id"] == "upstream-id"

    def test_generates_an_id_when_reuse_is_on_but_nothing_upstream_stamped_one(
        self, catalogue: type[CompleteCatalogue]
    ) -> None:
        client = build_client(reuse_request_state_id=True)

        assert client.get("/context").json()["request_id"]


class TestAccessLogging:
    def test_logs_one_access_record_per_request(self, client: TestClient, records: RecordingHandler) -> None:
        client.get("/ok")

        assert len(records.with_event_id(ACCESS_EVENT_ID)) == 1

    def test_the_access_record_carries_the_outcome(self, client: TestClient, records: RecordingHandler) -> None:
        client.get("/ok")

        record = records.with_event_id(ACCESS_EVENT_ID)[0]
        assert record.status_code == 200  # type: ignore[attr-defined]
        assert record.duration_ms >= 0  # type: ignore[attr-defined]
        assert record.name == "app.access"

    def test_uses_the_route_specific_event_id_when_the_catalogue_maps_one(
        self, client: TestClient, records: RecordingHandler
    ) -> None:
        client.delete("/resources/7")

        assert records.with_event_id("100702")

    def test_falls_back_to_the_generic_access_event_id_for_unmapped_routes(
        self, client: TestClient, records: RecordingHandler
    ) -> None:
        client.get("/ok")

        assert records.with_event_id(ACCESS_EVENT_ID)

    def test_still_logs_when_the_handler_raised(self, client: TestClient, records: RecordingHandler) -> None:
        client.get("/boom")

        assert records.with_event_id(ACCESS_EVENT_ID)[0].status_code is None  # type: ignore[attr-defined]

    def test_can_be_switched_off(self, catalogue: type[CompleteCatalogue], records: RecordingHandler) -> None:
        client = build_client(access_log=False)

        client.get("/ok")

        assert records.with_event_id(ACCESS_EVENT_ID) == []


@pytest.fixture
def capturing_client(catalogue: type[CompleteCatalogue]) -> TestClient:
    return build_client(capture_body_methods=("POST",))


class TestBodyCapture:
    def test_is_off_unless_the_application_asks_for_it(self, client: TestClient, records: RecordingHandler) -> None:
        """A request body is the likeliest place for data that must not be logged."""
        client.post("/ok", json={"card": "4111111111111111"})

        assert not hasattr(records.with_event_id(ACCESS_EVENT_ID)[0], "body")

    def test_captures_a_json_body_on_the_configured_methods(
        self, capturing_client: TestClient, records: RecordingHandler
    ) -> None:
        capturing_client.post("/ok", json={"name": "acme"})

        assert records.with_event_id(ACCESS_EVENT_ID)[0].body == {"name": "acme"}  # type: ignore[attr-defined]

    def test_keeps_an_unparsable_body_as_text(self, capturing_client: TestClient, records: RecordingHandler) -> None:
        capturing_client.post("/ok", content=b"not json")

        assert records.with_event_id(ACCESS_EVENT_ID)[0].body == "not json"  # type: ignore[attr-defined]

    def test_does_not_capture_bodies_on_other_methods(
        self, capturing_client: TestClient, records: RecordingHandler
    ) -> None:
        capturing_client.get("/ok")

        assert not hasattr(records.with_event_id(ACCESS_EVENT_ID)[0], "body")

    def test_truncates_a_body_past_the_cap_and_says_so(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        client = build_client(capture_body_methods=("POST",), max_body_bytes=8)

        client.post("/ok", content=b"0123456789abcdef")

        record = records.with_event_id(ACCESS_EVENT_ID)[0]
        assert record.body == "01234567"  # type: ignore[attr-defined]
        assert record.body_truncated is True  # type: ignore[attr-defined]

    def test_the_endpoint_can_still_read_the_body(self, capturing_client: TestClient) -> None:
        assert capturing_client.post("/echo", content=b"payload").json()["body"] == "payload"

    def test_the_endpoint_can_stream_the_body_after_capture(self, capturing_client: TestClient) -> None:
        assert capturing_client.post("/stream", content=b"payload").json()["body"] == "payload"

    async def test_capturing_leaves_the_receive_channel_alone(self) -> None:
        """Guards the hazard in replacing ``request._receive`` on capture.

        A body-replaying stub is both unnecessary and unsafe, so capturing must
        read the body and nothing more.
        """
        messages = [{"type": "http.request", "body": b"payload", "more_body": False}]

        async def receive() -> Any:
            return messages.pop(0)

        request = Request(
            {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""},
            receive,
        )

        assert await _read_body(request, 4096) == ("payload", False)
        assert request.receive is receive


class TestClientAddress:
    def test_reports_the_connection_address_by_default(self, client: TestClient) -> None:
        """X-Forwarded-For is caller controlled, so it is not believed by default."""
        body = client.get("/context", headers={"X-Forwarded-For": "203.0.113.7"}).json()

        assert body["ip"] != "203.0.113.7"

    def test_reads_the_forwarded_header_when_a_proxy_is_trusted(self, catalogue: type[CompleteCatalogue]) -> None:
        trusting = build_client(trust_forwarded_for=True)

        body = trusting.get("/context", headers={"X-Forwarded-For": "203.0.113.7"}).json()

        assert body["ip"] == "203.0.113.7"

    def test_takes_the_leftmost_entry_of_a_forwarded_chain(self, catalogue: type[CompleteCatalogue]) -> None:
        trusting = build_client(trust_forwarded_for=True)

        body = trusting.get("/context", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}).json()

        assert body["ip"] == "203.0.113.7"

    def test_falls_back_to_the_connection_when_the_header_is_not_an_address(
        self, catalogue: type[CompleteCatalogue]
    ) -> None:
        trusting = build_client(trust_forwarded_for=True)

        body = trusting.get("/context", headers={"X-Forwarded-For": "not-an-ip"}).json()

        assert body["ip"] not in ("not-an-ip", UNSET)


class TestCorrelationIdExpected:
    def test_logs_when_a_required_correlation_id_is_missing(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        client = build_client(correlation_id_expected=True)

        client.get("/ok")

        record = records.with_event_id(MISSING_CORRELATION_EVENT_ID)[0]
        assert record.endpoint == "/ok"  # type: ignore[attr-defined]
        assert record.method == "GET"  # type: ignore[attr-defined]

    def test_stays_quiet_when_the_correlation_id_is_present(
        self, catalogue: type[CompleteCatalogue], records: RecordingHandler
    ) -> None:
        client = build_client(correlation_id_expected=True)

        client.get("/ok", headers={CORRELATION_ID_HEADER: "corr-1"})

        assert records.with_event_id(MISSING_CORRELATION_EVENT_ID) == []

    def test_stays_quiet_when_no_correlation_id_is_expected(
        self, client: TestClient, records: RecordingHandler
    ) -> None:
        client.get("/ok")

        assert records.with_event_id(MISSING_CORRELATION_EVENT_ID) == []


class TestCatalogueResolution:
    def test_an_explicit_catalogue_is_used_without_registration(self, records: RecordingHandler) -> None:
        app = build_app()
        app.add_middleware(RequestContextMiddleware, catalogue=CompleteCatalogue)

        TestClient(app).get("/ok")

        assert records.with_event_id(ACCESS_EVENT_ID)

    def test_fails_loudly_when_no_catalogue_is_available(self, records: RecordingHandler) -> None:
        app = build_app()
        app.add_middleware(RequestContextMiddleware)
        client = TestClient(app)

        with pytest.raises(RuntimeError, match="no event catalogue registered"):
            client.get("/ok")


class TestBindRequestContext:
    def test_rebinds_the_context_after_the_middleware_has_torn_it_down(
        self, catalogue: type[CompleteCatalogue]
    ) -> None:
        seen: dict[str, Any] = {}

        async def handler(request: Request, exc: Exception) -> Response:
            with bind_request_context(request) as context:
                seen["context"] = collect_context()
                seen["request_id"] = context.request_id if context else None
            return JSONResponse({}, status_code=500)

        app = build_app()
        app.add_exception_handler(Exception, handler)
        app.add_middleware(RequestContextMiddleware)
        TestClient(app, raise_server_exceptions=False).get("/boom")

        assert seen["context"]["endpoint"] == "/boom"
        assert seen["request_id"] == seen["context"]["request_id"]

    def test_yields_none_for_a_request_that_never_reached_the_middleware(self) -> None:
        request = Request({"type": "http", "headers": [], "method": "GET", "path": "/", "state": {}})

        with bind_request_context(request) as context:
            assert context is None
            assert collect_context() == {}


class TestRestoreRequestContext:
    def _client(self, handler: Any, *, with_middleware: bool = True) -> TestClient:
        app = build_app()
        app.add_exception_handler(Exception, restore_request_context(handler))
        if with_middleware:
            app.add_middleware(RequestContextMiddleware)
        return TestClient(app, raise_server_exceptions=False)

    def test_binds_the_context_for_an_async_handler(self, catalogue: type[CompleteCatalogue]) -> None:
        seen: dict[str, Any] = {}

        async def handler(request: Request, exc: Exception) -> Response:
            seen.update(collect_context())
            return JSONResponse({}, status_code=500)

        self._client(handler).get("/boom", headers={CORRELATION_ID_HEADER: "corr-1"})

        assert seen["endpoint"] == "/boom"
        assert seen["correlation_id"] == "corr-1"

    def test_binds_the_context_for_a_sync_handler(self, catalogue: type[CompleteCatalogue]) -> None:
        seen: dict[str, Any] = {}

        def handler(request: Request, exc: Exception) -> Response:
            seen.update(collect_context())
            return JSONResponse({}, status_code=500)

        self._client(handler).get("/boom", headers={CORRELATION_ID_HEADER: "corr-1"})

        assert seen["endpoint"] == "/boom"
        assert seen["correlation_id"] == "corr-1"

    def test_echoes_the_correlation_headers_onto_the_response(self, catalogue: type[CompleteCatalogue]) -> None:
        async def handler(request: Request, exc: Exception) -> Response:
            return JSONResponse({}, status_code=500)

        response = self._client(handler).get("/boom", headers={CORRELATION_ID_HEADER: "corr-1"})

        assert response.status_code == 500
        assert response.headers[CORRELATION_ID_HEADER] == "corr-1"
        assert response.headers[REQUEST_ID_HEADER]

    def test_leaves_the_response_body_to_the_handler(self, catalogue: type[CompleteCatalogue]) -> None:
        async def handler(request: Request, exc: Exception) -> Response:
            return JSONResponse({"error": "Internal server error"}, status_code=500)

        assert self._client(handler).get("/boom").json() == {"error": "Internal server error"}

    def test_still_responds_for_a_request_that_never_reached_the_middleware(self) -> None:
        async def handler(request: Request, exc: Exception) -> Response:
            return JSONResponse({"context": collect_context()}, status_code=500)

        response = self._client(handler, with_middleware=False).get("/boom")

        assert response.status_code == 500
        assert response.json()["context"] == {}
        assert REQUEST_ID_HEADER not in response.headers


class TestRequestContext:
    def test_reports_unset_for_fields_it_does_not_carry(self) -> None:
        context = RequestContext(values={})

        assert context.request_id == UNSET
        assert context.correlation_id == UNSET
        assert context.endpoint == UNSET
