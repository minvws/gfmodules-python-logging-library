"""The whole integration. Everything else here is ordinary code that happens to log."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import gfmodules.logging as gflog
from fastapi_app import service
from fastapi_app.config import Settings
from fastapi_app.events import Log
from gfmodules.logging.exceptions import log_unhandled_exception
from gfmodules.logging.middleware import RequestContextMiddleware, restore_request_context

logger = logging.getLogger("app.api")

# Declaring the field is what makes the header survive to the record.
TENANT_ID = gflog.ContextField(name="tenant_id", header="X-Tenant-Id")


class CreateResource(BaseModel):
    resource_id: str
    owner_id: str
    created_by: str


def setup_logging(settings: Settings, *, strict_fields: bool = False) -> None:
    """The test suite passes ``strict_fields=True`` so a field that would reach
    no stream fails there rather than going quietly missing in production.
    """
    gflog.configure(
        config=settings.logging,
        loglevel=settings.app.loglevel,
        catalogue=Log,
        extra_context_fields=(TENANT_ID,),
        strict_fields=strict_fields,
    )
    gflog.install_excepthook(logger)
    gflog.install_signal_handlers()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with gflog.lifespan_logging(logger, version=settings.app.version, config_path="/etc/app/config.toml"):
            yield

    app = FastAPI(lifespan=lifespan)

    @app.post("/resources")
    async def create(body: CreateResource) -> Response:
        service.create_resource(body.resource_id, body.owner_id, body.created_by)
        return JSONResponse(status_code=201, content={"resource_id": body.resource_id})

    @app.delete("/resources/{resource_id}")
    async def delete(resource_id: str) -> Response:
        try:
            service.delete_resource(resource_id, reason="requested by owner")
        except service.UnknownResource:
            return JSONResponse(status_code=404, content={"error": "Unknown resource"})
        return JSONResponse({"resource_id": resource_id})

    @app.get("/boom")
    async def boom() -> Response:
        raise RuntimeError("something the application did not anticipate")

    @restore_request_context
    async def unhandled(request: Request, exc: Exception) -> Response:
        log_unhandled_exception(logger, request, exc)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    app.add_exception_handler(Exception, unhandled)

    # Added last so it runs outermost, wrapping every route and handler above.
    app.add_middleware(
        RequestContextMiddleware,
        correlation_id_expected=settings.logging.correlation_id_expected,
        # capture_body_methods stays unset: no reason to log a create call's contents.
        trust_forwarded_for=settings.logging.trust_forwarded_for,
    )
    return app
