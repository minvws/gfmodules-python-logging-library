import json
import logging
from typing import Any

import pytest

from gfmodules.logging.config import ConfigLogging
from gfmodules.logging.config_builder import LogConfigBuilder
from gfmodules.logging.filters import AppFilter, PublicInspectFilter, SiemFilter
from gfmodules.logging.formatter import JsonFormatter, PlainTextFormatter
from gfmodules.logging.streams import LoggingStreams

APP_ID = "example-service"
SYSLOG = "syslog-server:5514"
ADDRESS = ("syslog-server", 5514)

EXPECTED_SYSLOG_DOCUMENT: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "app_filter": {"()": AppFilter},
        "siem_filter": {"()": SiemFilter},
        "public_inspect_filter": {"()": PublicInspectFilter},
    },
    "formatters": {
        "json": {"()": JsonFormatter, "include_traces": False, "application_id": APP_ID},
        "json_traces": {"()": JsonFormatter, "include_traces": True, "application_id": APP_ID},
        "json_app": {
            "()": JsonFormatter,
            "include_traces": False,
            "stream": LoggingStreams.APP,
            "stream_id": "app",
            "application_id": APP_ID,
        },
        "json_siem": {
            "()": JsonFormatter,
            "include_traces": False,
            "stream": LoggingStreams.SIEM,
            "stream_id": "siem",
            "application_id": APP_ID,
        },
        "json_public_inspect": {
            "()": JsonFormatter,
            "include_traces": False,
            "stream": LoggingStreams.PUBLIC_INSPECT,
            "stream_id": "public_inspect",
            "application_id": APP_ID,
        },
        "json_debug": {
            "()": JsonFormatter,
            "include_traces": True,
            "stream_id": "debug",
            "application_id": APP_ID,
        },
        "plain": {"()": PlainTextFormatter},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "json_traces",
            "filters": ["app_filter"],
            "stream": "ext://sys.stdout",
        },
        "syslog_app": {
            "class": "logging.handlers.SysLogHandler",
            "address": ADDRESS,
            "formatter": "json_app",
            "filters": ["app_filter"],
        },
        "syslog_siem": {
            "class": "logging.handlers.SysLogHandler",
            "address": ADDRESS,
            "formatter": "json_siem",
            "filters": ["siem_filter"],
        },
        "syslog_public_inspect": {
            "class": "logging.handlers.SysLogHandler",
            "address": ADDRESS,
            "formatter": "json_public_inspect",
            "filters": ["public_inspect_filter"],
        },
        "syslog_debug": {
            "class": "logging.handlers.SysLogHandler",
            "address": ADDRESS,
            "formatter": "json_debug",
        },
    },
    "loggers": {
        "app": {
            "handlers": ["console", "syslog_app", "syslog_siem", "syslog_public_inspect", "syslog_debug"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn": {
            "handlers": ["console", "syslog_app", "syslog_debug"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console", "syslog_app", "syslog_debug"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {"handlers": [], "level": "CRITICAL", "propagate": False},
        "inject": {"level": "INFO", "propagate": True},
    },
    "root": {"handlers": ["console", "syslog_debug"], "level": "INFO"},
}


def build(config: ConfigLogging, loglevel: str = "INFO") -> dict[str, Any]:
    return LogConfigBuilder(logging_config=config, loglevel=loglevel).build()


def test_builds_the_expected_document_for_a_syslog_configuration() -> None:
    assert build(ConfigLogging(application_id=APP_ID, syslog_path=SYSLOG)) == EXPECTED_SYSLOG_DOCUMENT


class TestConsoleHandler:
    def test_uses_the_plain_formatter_when_debugging_in_the_console(self) -> None:
        console = build(ConfigLogging(debug_logs_in_console=True))["handlers"]["console"]

        assert console["formatter"] == "plain"
        assert console["level"] == "DEBUG"
        assert "filters" not in console

    def test_filters_to_the_app_stream_otherwise(self) -> None:
        console = build(ConfigLogging())["handlers"]["console"]

        assert console["filters"] == ["app_filter"]
        assert console["formatter"] == "json_traces"

    def test_drops_traces_when_the_configuration_disables_them(self) -> None:
        console = build(ConfigLogging(include_traces=False))["handlers"]["console"]

        assert console["formatter"] == "json"

    def test_honours_the_requested_log_level(self) -> None:
        conf = build(ConfigLogging(), loglevel="WARNING")

        assert conf["handlers"]["console"]["level"] == "WARNING"
        assert conf["loggers"]["app"]["level"] == "WARNING"
        assert conf["root"]["level"] == "WARNING"


class TestSyslogHandlers:
    def test_no_syslog_handlers_are_added_without_a_path(self) -> None:
        conf = build(ConfigLogging())

        assert list(conf["handlers"]) == ["console"]
        assert conf["loggers"]["app"]["handlers"] == ["console"]

    def test_each_stream_gets_its_own_handler_over_the_shared_channel(self) -> None:
        handlers = build(ConfigLogging(syslog_path=SYSLOG))["handlers"]

        assert set(handlers) == {"console", "syslog_app", "syslog_siem", "syslog_public_inspect", "syslog_debug"}
        for name in ("syslog_app", "syslog_siem", "syslog_public_inspect", "syslog_debug"):
            assert handlers[name]["address"] == ("syslog-server", 5514)

    def test_stream_handlers_carry_their_matching_filter(self) -> None:
        handlers = build(ConfigLogging(syslog_path=SYSLOG))["handlers"]

        assert handlers["syslog_app"]["filters"] == ["app_filter"]
        assert handlers["syslog_siem"]["filters"] == ["siem_filter"]
        assert handlers["syslog_public_inspect"]["filters"] == ["public_inspect_filter"]

    def test_the_debug_handler_is_unfiltered_so_it_sees_everything(self) -> None:
        handlers = build(ConfigLogging(syslog_path=SYSLOG))["handlers"]

        assert "filters" not in handlers["syslog_debug"]

    def test_parses_an_ipv6_host_correctly(self) -> None:
        handlers = build(ConfigLogging(syslog_path="fd00::1:5514"))["handlers"]

        assert handlers["syslog_debug"]["address"] == ("fd00::1", 5514)

    def test_a_debug_console_keeps_the_syslog_handlers(self) -> None:
        conf = build(ConfigLogging(syslog_path=SYSLOG, debug_logs_in_console=True))

        assert conf["handlers"]["console"]["formatter"] == "plain"
        assert set(conf["handlers"]) == {
            "console",
            "syslog_app",
            "syslog_siem",
            "syslog_public_inspect",
            "syslog_debug",
        }

    def test_only_the_debug_stream_reaches_the_root_logger(self) -> None:
        conf = build(ConfigLogging(syslog_path=SYSLOG))

        assert conf["root"]["handlers"] == ["console", "syslog_debug"]

    def test_siem_and_public_inspect_are_bound_to_the_app_logger_only(self) -> None:
        conf = build(ConfigLogging(syslog_path=SYSLOG))

        assert "syslog_siem" in conf["loggers"]["app"]["handlers"]
        assert "syslog_siem" not in conf["loggers"]["uvicorn"]["handlers"]
        assert "syslog_public_inspect" not in conf["loggers"]["uvicorn"]["handlers"]


class TestLoggers:
    def test_uvicorn_access_is_silenced_because_the_middleware_logs_access(self) -> None:
        access = build(ConfigLogging())["loggers"]["uvicorn.access"]

        assert access["handlers"] == []
        assert access["level"] == "CRITICAL"

    def test_existing_loggers_are_left_enabled(self) -> None:
        assert build(ConfigLogging())["disable_existing_loggers"] is False


class TestInjectIsFloored:
    @pytest.mark.parametrize("loglevel", ["DEBUG", "NOTSET", "NONSENSE"])
    def test_it_never_runs_below_info_however_verbose_the_application_is(self, loglevel: str) -> None:
        assert build(ConfigLogging(), loglevel=loglevel)["loggers"]["inject"]["level"] == "INFO"

    def test_an_application_quieter_than_the_floor_is_left_alone(self) -> None:
        assert build(ConfigLogging(), loglevel="ERROR")["loggers"]["inject"]["level"] == "ERROR"

    def test_what_survives_the_floor_still_reaches_the_debug_stream(self) -> None:
        logger = build(ConfigLogging(syslog_path=SYSLOG))["loggers"]["inject"]

        assert logger["propagate"] is True
        assert "handlers" not in logger


class TestApplicationIdStamping:
    def test_every_json_formatter_is_stamped(self) -> None:
        formatters = build(ConfigLogging(application_id=APP_ID, syslog_path=SYSLOG))["formatters"]

        json_formatters = [name for name, spec in formatters.items() if name != "plain"]
        assert json_formatters
        for name in json_formatters:
            assert formatters[name]["application_id"] == APP_ID

    def test_the_plain_formatter_is_never_stamped(self) -> None:
        formatters = build(ConfigLogging(application_id=APP_ID))["formatters"]

        assert "application_id" not in formatters["plain"]

    def test_nothing_is_stamped_without_an_application_id(self) -> None:
        formatters = build(ConfigLogging())["formatters"]

        assert all("application_id" not in spec for spec in formatters.values())


class TestStreamBoundFormatters:
    """Only a formatter that knows its stream applies the allow-list.

    A handler wired to a stream's filter still receives the right records, so a
    formatter left unbound looks correct until you inspect what it emitted.
    """

    def _format_for(self, name: str) -> dict[str, Any]:
        spec = dict(build(ConfigLogging(syslog_path=SYSLOG))["formatters"][name])
        spec.pop("()")
        record = logging.LogRecord("app.x", logging.INFO, "", 1, "published", (), None)
        record.event_id = "100800"
        record.stream = [LoggingStreams.PUBLIC_INSPECT, LoggingStreams.SIEM]
        record.field_streams = {
            LoggingStreams.PUBLIC_INSPECT: ("public_id",),
            LoggingStreams.SIEM: ("public_id",),
        }
        record.public_id = "p-1"
        record.internal_note = "not for either stream"
        return dict(json.loads(JsonFormatter(**spec).format(record))["message"])

    def test_public_inspect_drops_a_field_it_is_not_allow_listed_for(self) -> None:
        assert "internal_note" not in self._format_for("json_public_inspect")

    def test_siem_drops_a_field_it_is_not_allow_listed_for(self) -> None:
        assert "internal_note" not in self._format_for("json_siem")

    def test_debug_keeps_everything_because_it_is_the_unrouted_view(self) -> None:
        assert "internal_note" in self._format_for("json_debug")
