"""What the configured logger tree delivers, handler by handler.

Capturing on a logger of one's own choosing flattens the tree and hides where a
record would really have gone. These run the real ``dictConfig`` and read what
each syslog handler received, so a record emitted outside the ``app`` tree shows
up as the missing stream it is.
"""

import json
import logging
import logging.handlers
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

import gfmodules.logging as gflog
from gfmodules.logging.middleware import RequestContextMiddleware
from tests.helpers.catalogue import CompleteCatalogue


@pytest.fixture
def delivered(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every payload the configured syslog handlers hand to the socket.

    Patching ``emit`` leaves ``Handler.handle`` in place, so each handler's own
    filter still decides what reaches here.
    """
    payloads: list[dict[str, Any]] = []

    def record(handler: logging.handlers.SysLogHandler, entry: logging.LogRecord) -> None:
        payloads.append(json.loads(handler.format(entry)))

    monkeypatch.setattr(logging.handlers.SysLogHandler, "emit", record)
    return payloads


def configure(loglevel: str = "INFO", logger_root: str = gflog.DEFAULT_LOGGER_ROOT) -> None:
    gflog.configure(
        config=gflog.ConfigLogging(syslog_path="localhost:1514", application_id="routing-test", access_logs=True),
        loglevel=loglevel,
        catalogue=CompleteCatalogue,
        logger_root=logger_root,
    )


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/resources")
    async def list_resources() -> Response:
        return JSONResponse({"resources": []})

    app.add_middleware(RequestContextMiddleware, correlation_id_expected=True)
    return app


def streams_for(payloads: list[dict[str, Any]], event_id: str) -> set[str]:
    return {payload["stream_id"] for payload in payloads if payload["event_id"] == event_id}


def streams_reporting(payloads: list[dict[str, Any]], phrase: str) -> set[str]:
    """The streams the library's own records reach.

    Delivery is never the assertion here: a record reaching the debug handler
    and nothing else is the failure, and it looks like success to anything that
    only asks whether something was logged.
    """
    return {payload["stream_id"] for payload in payloads if phrase in payload["event_description"]}


class TestLibraryInternalEvents:
    def test_the_missing_correlation_id_event_reaches_the_streams_it_declares(
        self, delivered: list[dict[str, Any]]
    ) -> None:
        configure()

        with TestClient(build_app()) as client:
            client.get("/resources")

        event = CompleteCatalogue.SYS_MISSING_CORRELATION_ID
        assert streams_for(delivered, event.event_id) == {"app", "siem", "debug"}

    def test_an_internal_debug_message_reaches_the_debug_stream_only(self, delivered: list[dict[str, Any]]) -> None:
        configure(loglevel="DEBUG")

        logging.getLogger(gflog.internal_logger_name()).debug("internal detail")

        assert {payload["stream_id"] for payload in delivered} == {"debug"}

    def test_the_internal_logger_follows_a_renamed_root(self, delivered: list[dict[str, Any]]) -> None:
        configure(logger_root="svc")

        assert gflog.internal_logger_name() == "svc.internal"

        with TestClient(build_app()) as client:
            client.get("/resources")

        event = CompleteCatalogue.SYS_MISSING_CORRELATION_ID
        assert streams_for(delivered, event.event_id) == {"app", "siem", "debug"}


class TestApplicationEvents:
    def test_an_application_event_reaches_the_streams_it_declares(self, delivered: list[dict[str, Any]]) -> None:
        configure()

        gflog.emit(
            logging.getLogger("app.service"),
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "r-1", "owner_id": "o-1", "created_by": "alice"},
        )

        event = CompleteCatalogue.RESOURCE_CREATED
        assert streams_for(delivered, event.event_id) >= {"app", "siem"}

    def test_the_access_record_reaches_the_app_stream(self, delivered: list[dict[str, Any]]) -> None:
        configure()

        with TestClient(build_app()) as client:
            client.get("/resources", headers={gflog.CORRELATION_ID_HEADER: "corr-1"})

        assert "app" in streams_for(delivered, CompleteCatalogue.ACCESS_REQUEST.event_id)


class TestARenamedRoot:
    def test_an_application_logging_under_its_own_root_reaches_every_stream(
        self, delivered: list[dict[str, Any]]
    ) -> None:
        configure(logger_root="svc")

        gflog.emit(
            logging.getLogger("svc.service"),
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "r-1", "owner_id": "o-1", "created_by": "alice"},
        )

        assert streams_for(delivered, CompleteCatalogue.RESOURCE_CREATED.event_id) >= {"app", "siem"}

    def test_the_old_root_stops_being_routed(self, delivered: list[dict[str, Any]]) -> None:
        """Renaming the root moves the tree; it does not add a second one."""
        configure(logger_root="svc")

        gflog.emit(
            logging.getLogger("app.service"),
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "r-1"},
        )

        assert streams_for(delivered, CompleteCatalogue.RESOURCE_CREATED.event_id) == {"debug"}

    def test_the_access_logger_follows_the_root(self, delivered: list[dict[str, Any]]) -> None:
        configure(logger_root="svc")

        with TestClient(build_app()) as client:
            client.get("/resources", headers={gflog.CORRELATION_ID_HEADER: "corr-1"})

        assert "app" in streams_for(delivered, CompleteCatalogue.ACCESS_REQUEST.event_id)

    @pytest.mark.parametrize("name", ["", ".svc", "svc."])
    def test_an_unusable_root_is_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="invalid logger root"):
            configure(logger_root=name)


def misrouting_reports(payloads: list[dict[str, Any]]) -> list[str]:
    return [payload["event_description"] for payload in payloads if "is outside the" in payload["event_description"]]


class TestLoggingOutsideTheRoot:
    """The failure a configurable root does not remove: logging outside it."""

    def test_an_event_logged_outside_the_root_is_reported(self, delivered: list[dict[str, Any]]) -> None:
        configure(logger_root="svc")

        gflog.emit(
            logging.getLogger("app.service"),
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "r-1"},
        )

        assert "logger app.service is outside the svc tree" in misrouting_reports(delivered)[0]

    def test_it_is_reported_once_per_logger(self, delivered: list[dict[str, Any]]) -> None:
        """A warning per record would be worse than the silence it replaces."""
        configure(logger_root="svc")
        stray = logging.getLogger("app.service")

        for _ in range(3):
            gflog.emit(stray, CompleteCatalogue.RESOURCE_CREATED, "resource created", fields={"resource_id": "r-1"})

        assert len({report for report in misrouting_reports(delivered)}) == 1

    def test_the_report_reaches_the_app_stream(self, delivered: list[dict[str, Any]]) -> None:
        """It has to arrive where someone watching an empty stream is looking."""
        configure(logger_root="svc")

        gflog.emit(
            logging.getLogger("app.service"),
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "r-1"},
        )

        assert streams_reporting(delivered, "is outside the") == {"app", "debug"}

    def test_a_correctly_routed_event_is_not_reported(self, delivered: list[dict[str, Any]]) -> None:
        configure(logger_root="svc")

        gflog.emit(
            logging.getLogger("svc.service"),
            CompleteCatalogue.RESOURCE_CREATED,
            "resource created",
            fields={"resource_id": "r-1"},
        )

        assert misrouting_reports(delivered) == []


class TestAnUnreachableLogServer:
    """Boot fails rather than running on with an audit obligation unmet."""

    def test_the_error_names_the_setting_that_needs_fixing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unreachable(*args: Any, **kwargs: Any) -> None:
            raise OSError("temporary failure in name resolution")

        monkeypatch.setattr(logging.handlers.SysLogHandler, "__init__", unreachable)

        with pytest.raises(ValueError, match="syslog_path 'localhost:1514'"):
            configure()

    def test_a_failure_that_is_not_the_log_server_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(*args: Any, **kwargs: Any) -> None:
            raise OSError("no console")

        monkeypatch.setattr(logging.StreamHandler, "__init__", broken)

        with pytest.raises(ValueError, match="Unable to configure handler"):
            gflog.configure(config=gflog.ConfigLogging(), loglevel="INFO", catalogue=CompleteCatalogue)


class TestApplicationId:
    """Every application shares the syslog channel, so records need to say which."""

    def test_configure_reports_a_missing_application_id_on_the_app_stream(
        self, delivered: list[dict[str, Any]]
    ) -> None:
        """A warning about logging that only the debug stream carries warns nobody."""
        gflog.configure(
            config=gflog.ConfigLogging(syslog_path="localhost:1514"),
            loglevel="INFO",
            catalogue=CompleteCatalogue,
        )

        assert streams_reporting(delivered, "no application_id is configured") == {"app", "debug"}

    def test_it_stays_quiet_when_nothing_reaches_syslog(self, delivered: list[dict[str, Any]]) -> None:
        gflog.configure(
            config=gflog.ConfigLogging(),
            loglevel="INFO",
            catalogue=CompleteCatalogue,
        )

        assert delivered == []

    def test_it_stays_quiet_once_configured(self, delivered: list[dict[str, Any]]) -> None:
        configure()

        assert streams_reporting(delivered, "no application_id") == set()
