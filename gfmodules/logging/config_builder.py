import logging
from typing import Any

from gfmodules.logging.config import ConfigLogging
from gfmodules.logging.filters import AppFilter, PublicInspectFilter, SiemFilter
from gfmodules.logging.formatter import JsonFormatter, PlainTextFormatter
from gfmodules.logging.loggers import active_logger_root
from gfmodules.logging.streams import LoggingStreams

CONSOLE_STREAMS = ("app", "siem", "debug")


def _at_least(loglevel: str, floor: int) -> str:
    numeric = logging.getLevelNamesMapping().get(loglevel.upper())
    return loglevel if numeric is not None and numeric >= floor else logging.getLevelName(floor)


class LogConfigBuilder:
    """Reads the registered logger root when ``build()`` runs, not before."""

    def __init__(
        self,
        logging_config: ConfigLogging,
        loglevel: str = "INFO",
    ) -> None:
        self.loglevel = loglevel
        self.logging_config = logging_config

    def _syslog_handler(self, path: str, formatter: str, filters: list[str] | None = None) -> dict[str, Any]:
        host, port_str = path.rsplit(":", 1)
        cfg: dict[str, Any] = {
            "class": "logging.handlers.SysLogHandler",
            "address": (host, int(port_str)),
            "formatter": formatter,
        }
        if filters:
            cfg["filters"] = filters
        return cfg

    def build(self) -> dict[str, Any]:
        traces = self.logging_config.include_traces
        conf: dict[str, Any] = {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "app_filter": {"()": AppFilter},
                "siem_filter": {"()": SiemFilter},
                "public_inspect_filter": {"()": PublicInspectFilter},
            },
            "formatters": {
                # Only a formatter bound to a stream applies that stream's field
                # allow-list, and its stream_id is how the log server splits the
                # shared syslog channel again.
                "json_app": {
                    "()": JsonFormatter,
                    "include_traces": False,
                    "stream": LoggingStreams.APP,
                    "stream_id": "app",
                },
                "json_siem": {
                    "()": JsonFormatter,
                    "include_traces": False,
                    "stream": LoggingStreams.SIEM,
                    "stream_id": "siem",
                },
                "json_public_inspect": {
                    "()": JsonFormatter,
                    "include_traces": False,
                    "stream": LoggingStreams.PUBLIC_INSPECT,
                    "stream_id": "public_inspect",
                },
                "json_debug": {
                    "()": JsonFormatter,
                    "include_traces": True,
                    "stream_id": "debug",
                },
                # The console is plain text only, so these are the only formatters
                # ``include_traces`` still has anything to say about.
                "plain_app": {
                    "()": PlainTextFormatter,
                    "include_traces": traces,
                    "stream": LoggingStreams.APP,
                    "stream_id": "app",
                },
                "plain_siem": {
                    "()": PlainTextFormatter,
                    "include_traces": traces,
                    "stream": LoggingStreams.SIEM,
                    "stream_id": "siem",
                },
                "plain_debug": {
                    "()": PlainTextFormatter,
                    "include_traces": traces,
                    "stream_id": "debug",
                },
            },
            "handlers": {},
            "loggers": {
                active_logger_root(): {
                    "handlers": [],
                    "level": self.loglevel,
                    "propagate": False,
                },
                "uvicorn": {
                    "handlers": [],
                    "level": self.loglevel,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": [],
                    "level": self.loglevel,
                    "propagate": False,
                },
                # Silenced because RequestContextMiddleware logs access itself.
                "uvicorn.access": {
                    "handlers": [],
                    "level": "CRITICAL",
                    "propagate": False,
                },
                # Floored rather than silenced, and left propagating
                # Would leak otherwise as inject logs every binding at DEBUG level
                "inject": {
                    "level": _at_least(self.loglevel, logging.INFO),
                    "propagate": True,
                },
            },
            "root": {"handlers": [], "level": self.loglevel},
        }

        if self.logging_config.application_id:
            for formatter in conf["formatters"].values():
                if formatter["()"] is JsonFormatter:
                    formatter["application_id"] = self.logging_config.application_id

        self._add_console_streams(conf)
        self._add_log_handlers(conf)

        return conf

    def _selected_console_streams(self) -> list[str]:
        """One stdout handler per stream, so a stream named twice is still listed once.

        The default lives on ``ConfigLogging.console_streams``, so an empty selection
        is taken at face value: it asks for a silent stdout.
        """
        unknown = [name for name in self.logging_config.console_streams if name not in CONSOLE_STREAMS]
        if unknown:
            raise ValueError(f"unknown console_streams {unknown}, choose from {list(CONSOLE_STREAMS)}")

        return list(dict.fromkeys(self.logging_config.console_streams))

    def _add_console_streams(self, conf: dict[str, Any]) -> None:
        app_logger_handlers = conf["loggers"][active_logger_root()]["handlers"]
        uvicorn_handlers = conf["loggers"]["uvicorn"]["handlers"]
        uvicorn_error_handlers = conf["loggers"]["uvicorn.error"]["handlers"]
        root_handlers = conf["root"]["handlers"]

        bindings: dict[str, tuple[str, str | None, str, list[list[str]]]] = {
            "app": (
                "plain_app",
                "app_filter",
                self.loglevel,
                [app_logger_handlers, uvicorn_handlers, uvicorn_error_handlers],
            ),
            "siem": ("plain_siem", "siem_filter", self.loglevel, [app_logger_handlers]),
            "debug": (
                "plain_debug",
                None,
                "DEBUG",
                [app_logger_handlers, uvicorn_handlers, uvicorn_error_handlers, root_handlers],
            ),
        }

        for stream_name in self._selected_console_streams():
            formatter, filter_name, level, logger_handler_lists = bindings[stream_name]
            handler_name = f"console_{stream_name}"
            handler: dict[str, Any] = {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": formatter,
                "stream": "ext://sys.stdout",
            }
            if filter_name:
                handler["filters"] = [filter_name]
            conf["handlers"][handler_name] = handler
            for logger_handlers in logger_handler_lists:
                logger_handlers.append(handler_name)

    def _add_log_handlers(self, conf: dict[str, Any]) -> None:
        path = self.logging_config.syslog_path
        if not path:
            return

        app_logger_handlers = conf["loggers"][active_logger_root()]["handlers"]
        uvicorn_handlers = conf["loggers"]["uvicorn"]["handlers"]
        uvicorn_error_handlers = conf["loggers"]["uvicorn.error"]["handlers"]

        conf["handlers"]["syslog_app"] = self._syslog_handler(path, formatter="json_app", filters=["app_filter"])
        app_logger_handlers.append("syslog_app")
        uvicorn_handlers.append("syslog_app")
        uvicorn_error_handlers.append("syslog_app")

        conf["handlers"]["syslog_siem"] = self._syslog_handler(path, formatter="json_siem", filters=["siem_filter"])
        app_logger_handlers.append("syslog_siem")

        conf["handlers"]["syslog_public_inspect"] = self._syslog_handler(
            path, formatter="json_public_inspect", filters=["public_inspect_filter"]
        )
        app_logger_handlers.append("syslog_public_inspect")

        conf["handlers"]["syslog_debug"] = self._syslog_handler(path, formatter="json_debug")
        app_logger_handlers.append("syslog_debug")
        uvicorn_handlers.append("syslog_debug")
        uvicorn_error_handlers.append("syslog_debug")
        conf["root"]["handlers"].append("syslog_debug")
