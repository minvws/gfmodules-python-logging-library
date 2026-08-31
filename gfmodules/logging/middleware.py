import inspect
import ipaddress
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from gfmodules.logging.context import (
    CLIENT_IP_HEADER,
    CLIENT_TRACE_ID_HEADER,
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    UNSET,
    bind_context,
    extract_context,
)
from gfmodules.logging.events import EventCatalogue
from gfmodules.logging.loggers import access_logger_name, internal_logger_name
from gfmodules.logging.registry import access_logs_enabled, resolve_catalogue

__all__ = [
    "RequestContext",
    "RequestContextMiddleware",
    "bind_request_context",
    "restore_request_context",
]

_REQUEST_CONTEXT_STATE_KEY = "request_context"


# Resolved per call: which tree these names sit in is only settled once configure() has run.
def _access_logger() -> logging.Logger:
    return logging.getLogger(access_logger_name())


def _internal_logger() -> logging.Logger:
    return logging.getLogger(internal_logger_name())


@dataclass(frozen=True)
class RequestContext:
    values: Mapping[str, str]

    @property
    def request_id(self) -> str:
        return self.values.get("request_id", UNSET)

    @property
    def client_trace_id(self) -> str:
        return self.values.get("client_trace_id", UNSET)

    @property
    def correlation_id(self) -> str:
        return self.values.get("correlation_id", UNSET)

    @property
    def endpoint(self) -> str:
        return self.values.get("endpoint", UNSET)

    @property
    def method(self) -> str:
        return self.values.get("method", UNSET)

    @classmethod
    def from_request(
        cls,
        request: Request,
        *,
        reuse_request_state_id: bool = False,
        trust_forwarded_for: bool = False,
    ) -> "RequestContext":
        values = extract_context(request.headers)
        values["request_id"] = _request_id(request, reuse_request_state_id)
        values["ip"] = _client_ip(request, trust_forwarded_for)
        values["endpoint"] = request.url.path
        values["method"] = request.method
        return cls(values=values)

    def apply_to(self, response: Response) -> None:
        """Echo the correlation headers back to the caller."""
        response.headers[REQUEST_ID_HEADER] = self.request_id
        if self.client_trace_id != UNSET:
            response.headers[CLIENT_TRACE_ID_HEADER] = self.client_trace_id
        if self.correlation_id != UNSET:
            response.headers[CORRELATION_ID_HEADER] = self.correlation_id


def _client_ip(request: Request, trust_forwarded_for: bool) -> str:
    """``X-Forwarded-For`` is set by the caller, so anyone can claim any address
    with it. It is read only where the application trusts a proxy to rewrite it.
    """
    if trust_forwarded_for:
        forwarded = request.headers.get(CLIENT_IP_HEADER, "").split(",")[0].strip()
        if forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                _internal_logger().debug("%s did not carry a usable address", CLIENT_IP_HEADER)
    return request.client.host if request.client else UNSET


def _request_id(request: Request, reuse_request_state_id: bool) -> str:
    if not reuse_request_state_id:
        return str(uuid.uuid4())
    if "id" not in request.state:
        request.state["id"] = uuid.uuid4()
    return str(request.state["id"])


@contextmanager
def bind_request_context(request: Request) -> Generator[RequestContext | None]:
    """Rebind the context a request was handled with, or ``None`` if it has none.

    Exception handlers run in ``ServerErrorMiddleware``, outside this
    middleware, so by the time they execute the context has been torn down.
    """
    context: RequestContext | None = getattr(request.state, _REQUEST_CONTEXT_STATE_KEY, None)
    if context is None:
        yield None
        return
    with bind_context(context.values):
        yield context


_HandlerT = TypeVar("_HandlerT", bound=Callable[[Request, Exception], Any])


def restore_request_context(handler: _HandlerT) -> _HandlerT:
    """Runs the handler with its request's context, echoing the correlation headers onto its response."""
    if inspect.iscoroutinefunction(handler):

        @wraps(handler)
        async def async_wrapper(request: Request, exc: Exception) -> Response:
            with bind_request_context(request) as context:
                response = cast(Response, await cast(Callable[..., Awaitable[Any]], handler)(request, exc))
                if context is not None:
                    context.apply_to(response)
                return response

        return cast(_HandlerT, async_wrapper)

    @wraps(handler)
    def wrapper(request: Request, exc: Exception) -> Response:
        with bind_request_context(request) as context:
            response = cast(Response, handler(request, exc))
            if context is not None:
                context.apply_to(response)
            return response

    return cast(_HandlerT, wrapper)


def _router_path(request: Request) -> str:
    route = request.scope.get("route")
    if route and hasattr(route, "path"):
        return str(route.path)
    return UNSET


async def _read_body(request: Request, max_bytes: int) -> tuple[str, bool]:
    """Read up to ``max_bytes`` of the body, leaving it readable by the endpoint.

    Reading is enough, because under ``BaseHTTPMiddleware`` the cached request
    replays its ``_body`` downstream. Replacing ``request._receive`` with a
    replaying stub is not merely redundant but unsafe: once the body is
    consumed, ``wrapped_receive`` expects an ``http.disconnect`` from
    ``receive()`` and raises on anything else.
    """
    body = await request.body()
    return body[:max_bytes].decode("utf-8", errors="replace"), len(body) > max_bytes


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Everything logged while a request is handled picks up its request id,
    client ip, endpoint, method and correlation metadata without being passed them.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        catalogue: type[EventCatalogue] | None = None,
        correlation_id_expected: bool = False,
        capture_body_methods: Sequence[str] = (),
        max_body_bytes: int = 4096,
        reuse_request_state_id: bool = False,
        trust_forwarded_for: bool = False,
    ) -> None:
        super().__init__(app)
        self.catalogue = catalogue
        self.correlation_id_expected = correlation_id_expected
        # Off unless asked for: a body is the likeliest place for the data an
        # application least wants logged, and the console applies no allow-list.
        self.capture_body_methods = tuple(method.upper() for method in capture_body_methods)
        self.max_body_bytes = max_body_bytes
        self.reuse_request_state_id = reuse_request_state_id
        self.trust_forwarded_for = trust_forwarded_for

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        catalogue = resolve_catalogue(self.catalogue)
        context = RequestContext.from_request(
            request,
            reuse_request_state_id=self.reuse_request_state_id,
            trust_forwarded_for=self.trust_forwarded_for,
        )
        setattr(request.state, _REQUEST_CONTEXT_STATE_KEY, context)

        with bind_context(context.values):
            if self.correlation_id_expected and context.correlation_id == UNSET:
                catalogue.event(
                    _internal_logger(),
                    catalogue.SYS_MISSING_CORRELATION_ID,
                    f"request arrived without {CORRELATION_ID_HEADER}",
                    fields={"endpoint": context.endpoint, "method": context.method},
                )

            body = (
                await _read_body(request, self.max_body_bytes) if request.method in self.capture_body_methods else None
            )
            response: Response | None = None
            start = time.perf_counter()
            try:
                response = await call_next(request)
                context.apply_to(response)
                return response
            finally:
                if access_logs_enabled():
                    self._log_access(catalogue, request, response, body, start)

    def _log_access(
        self,
        catalogue: type[EventCatalogue],
        request: Request,
        response: Response | None,
        body: tuple[str, bool] | None,
        start: float,
    ) -> None:
        fields: dict[str, Any] = {
            "status_code": response.status_code if response is not None else None,
            "duration_ms": round((time.perf_counter() - start) * 1000),
        }
        if body is not None:
            text, truncated = body
            # A truncated body is no longer parseable, so it stays a string.
            fields["body"] = text if truncated else _decode_body(text)
            if truncated:
                fields["body_truncated"] = True
        catalogue.event(
            _access_logger(),
            catalogue.ACCESS_REQUEST,
            "access",
            fields=fields,
            event_id=catalogue.access_event_id.get((request.method, _router_path(request))),
        )


def _decode_body(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        _internal_logger().debug(exc.msg)
        return body
