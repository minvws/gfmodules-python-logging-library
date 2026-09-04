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
        "plain_app": {
            "()": PlainTextFormatter,
            "include_traces": True,
            "stream": LoggingStreams.APP,
            "stream_id": "app",
        },
        "plain_siem": {
            "()": PlainTextFormatter,
            "include_traces": True,
            "stream": LoggingStreams.SIEM,
            "stream_id": "siem",
        },
        "plain_debug": {
            "()": PlainTextFormatter,
            "include_traces": True,
            "stream_id": "debug",
        },
    },
    "handlers": {
        "console_app": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "plain_app",
            "filters": ["app_filter"],
            "stream": "ext://sys.stdout",
        },
        "console_siem": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "plain_siem",
            "filters": ["siem_filter"],
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
            "handlers": [
                "console_app",
                "console_siem",
                "syslog_app",
                "syslog_siem",
                "syslog_public_inspect",
                "syslog_debug",
            ],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn": {
            "handlers": ["console_app", "syslog_app", "syslog_debug"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console_app", "syslog_app", "syslog_debug"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {"handlers": [], "level": "CRITICAL", "propagate": False},
        "inject": {"level": "INFO", "propagate": True},
    },
    "root": {"handlers": ["syslog_debug"], "level": "INFO"},
}


def build(config: ConfigLogging, loglevel: str = "INFO") -> dict[str, Any]:
    return LogConfigBuilder(logging_config=config, loglevel=loglevel).build()


def test_builds_the_expected_document_for_a_syslog_configuration() -> None:
    assert build(ConfigLogging(application_id=APP_ID, syslog_path=SYSLOG)) == EXPECTED_SYSLOG_DOCUMENT


def console_handlers(conf: dict[str, Any]) -> dict[str, Any]:
    return {name: spec for name, spec in conf["handlers"].items() if name.startswith("console")}


class TestTheConsoleIsPlainTextOnly:
    """stdout is for a human reading a terminal; the log server reads syslog."""

    def test_no_console_handler_formats_as_json(self) -> None:
        conf = build(ConfigLogging(syslog_path=SYSLOG, console_streams=["app", "siem", "debug"]))

        for spec in console_handlers(conf).values():
            assert conf["formatters"][spec["formatter"]]["()"] is PlainTextFormatter

    def test_the_json_formatters_that_only_the_console_used_are_gone(self) -> None:
        formatters = build(ConfigLogging(syslog_path=SYSLOG))["formatters"]

        assert "json" not in formatters
        assert "json_traces" not in formatters

    def test_every_console_handler_writes_to_stdout(self) -> None:
        conf = build(ConfigLogging(console_streams=["app", "siem", "debug"]))

        for spec in console_handlers(conf).values():
            assert spec["stream"] == "ext://sys.stdout"


class TestTheDefaultConsole:
    def test_it_carries_the_app_and_siem_streams_as_plain_text(self) -> None:
        conf = build(ConfigLogging())

        assert list(console_handlers(conf)) == ["console_app", "console_siem"]
        assert conf["handlers"]["console_app"]["formatter"] == "plain_app"
        assert conf["handlers"]["console_app"]["filters"] == ["app_filter"]
        assert conf["handlers"]["console_siem"]["formatter"] == "plain_siem"
        assert conf["handlers"]["console_siem"]["filters"] == ["siem_filter"]

    def test_a_siem_only_event_is_no_longer_invisible_in_the_terminal(self) -> None:
        """The default used to carry app alone, so a SIEM-only event read as
        "nothing was logged" during development."""
        conf = build(ConfigLogging())

        assert "console_siem" in conf["loggers"]["app"]["handlers"]

    def test_the_debug_stream_is_not_on_by_default(self) -> None:
        conf = build(ConfigLogging())

        assert "console_debug" not in console_handlers(conf)
        assert conf["root"]["handlers"] == []

    def test_honours_the_requested_log_level(self) -> None:
        conf = build(ConfigLogging(), loglevel="WARNING")

        assert conf["handlers"]["console_app"]["level"] == "WARNING"
        assert conf["handlers"]["console_siem"]["level"] == "WARNING"
        assert conf["loggers"]["app"]["level"] == "WARNING"
        assert conf["root"]["level"] == "WARNING"


class TestConsoleStreamSelection:
    def test_an_explicit_selection_replaces_the_default_rather_than_adding_to_it(self) -> None:
        """Otherwise the app stream prints twice, once per handler."""
        conf = build(ConfigLogging(console_streams=["siem"]))

        assert list(console_handlers(conf)) == ["console_siem"]

    def test_each_selected_stream_gets_its_own_handler(self) -> None:
        conf = build(ConfigLogging(console_streams=["app", "siem", "debug"]))

        assert set(console_handlers(conf)) == {"console_app", "console_siem", "console_debug"}

    def test_a_stream_is_bound_to_a_logger_exactly_once(self) -> None:
        handlers = build(ConfigLogging(console_streams=["app", "siem", "debug"]))["loggers"]["app"]["handlers"]

        assert handlers == ["console_app", "console_siem", "console_debug"]

    def test_the_siem_stream_stays_off_the_uvicorn_loggers(self) -> None:
        conf = build(ConfigLogging(console_streams=["app", "siem"]))

        assert conf["loggers"]["uvicorn"]["handlers"] == ["console_app"]

    def test_only_the_debug_stream_reaches_the_root_logger(self) -> None:
        assert build(ConfigLogging(console_streams=["app"]))["root"]["handlers"] == []
        assert build(ConfigLogging(console_streams=["debug"]))["root"]["handlers"] == ["console_debug"]

    def test_the_debug_stream_is_unfiltered_so_it_sees_everything(self) -> None:
        console = build(ConfigLogging(console_streams=["debug"]))["handlers"]["console_debug"]

        assert "filters" not in console

    def test_an_unknown_stream_is_rejected_rather_than_silently_ignored(self) -> None:
        with pytest.raises(ValueError, match="nonsense"):
            build(ConfigLogging(console_streams=["nonsense"]))

    def test_an_empty_selection_leaves_stdout_quiet(self) -> None:
        conf = build(ConfigLogging(console_streams=[]))

        assert console_handlers(conf) == {}
        assert conf["loggers"]["app"]["handlers"] == []
        assert conf["root"]["handlers"] == []

    def test_an_empty_selection_still_reaches_the_log_server(self) -> None:
        conf = build(ConfigLogging(syslog_path=SYSLOG, console_streams=[]))

        assert console_handlers(conf) == {}
        assert conf["loggers"]["app"]["handlers"] == [
            "syslog_app",
            "syslog_siem",
            "syslog_public_inspect",
            "syslog_debug",
        ]

    def test_a_stream_named_twice_still_gets_one_handler(self) -> None:
        conf = build(ConfigLogging(console_streams=["debug", "debug"]))

        assert list(console_handlers(conf)) == ["console_debug"]
        assert conf["loggers"]["app"]["handlers"] == ["console_debug"]


class TestIncludeTraces:
    def test_the_console_formatters_keep_traces_by_default(self) -> None:
        formatters = build(ConfigLogging())["formatters"]

        assert formatters["plain_app"]["include_traces"] is True

    def test_disabling_traces_reaches_every_console_formatter(self) -> None:
        formatters = build(ConfigLogging(include_traces=False))["formatters"]

        for name in ("plain_app", "plain_siem", "plain_debug"):
            assert formatters[name]["include_traces"] is False


class TestSyslogHandlers:
    def test_no_syslog_handlers_are_added_without_a_path(self) -> None:
        conf = build(ConfigLogging())

        assert list(conf["handlers"]) == ["console_app", "console_siem"]
        assert conf["loggers"]["app"]["handlers"] == ["console_app", "console_siem"]

    def test_each_stream_gets_its_own_handler_over_the_shared_channel(self) -> None:
        handlers = build(ConfigLogging(syslog_path=SYSLOG))["handlers"]

        assert set(handlers) == {
            "console_app",
            "console_siem",
            "syslog_app",
            "syslog_siem",
            "syslog_public_inspect",
            "syslog_debug",
        }
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
        conf = build(ConfigLogging(syslog_path=SYSLOG, console_streams=["debug"]))

        assert conf["handlers"]["console_debug"]["formatter"] == "plain_debug"
        assert set(conf["handlers"]) == {
            "console_debug",
            "syslog_app",
            "syslog_siem",
            "syslog_public_inspect",
            "syslog_debug",
        }

    def test_only_the_debug_stream_reaches_the_root_logger(self) -> None:
        conf = build(ConfigLogging(syslog_path=SYSLOG))

        assert conf["root"]["handlers"] == ["syslog_debug"]

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

        json_formatters = [name for name, spec in formatters.items() if spec.get("()") is JsonFormatter]
        assert json_formatters
        for name in json_formatters:
            assert formatters[name]["application_id"] == APP_ID

    def test_the_plain_formatters_are_never_stamped(self) -> None:
        formatters = build(ConfigLogging(application_id=APP_ID))["formatters"]

        for name in ("plain_app", "plain_siem", "plain_debug"):
            assert "application_id" not in formatters[name]

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
