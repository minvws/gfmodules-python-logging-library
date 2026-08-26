from typing import Any

from gfmodules.logging.config import ConfigLogging
from gfmodules.logging.filters import AppFilter, PublicInspectFilter, SiemFilter
from gfmodules.logging.formatter import JsonFormatter, PlainTextFormatter
from gfmodules.logging.loggers import active_logger_root
from gfmodules.logging.streams import LoggingStreams


class LogConfigBuilder:
    """Reads the registered logger root when ``build()`` runs, not before."""

    def __init__(
        self,
        logging_config: ConfigLogging,
        loglevel: str = "INFO",
    ) -> None:
        self.loglevel = loglevel
        self.logging_config = logging_config

    def _syslog_handler(self, path: str, formatter: str = "json", filters: list[str] | None = None) -> dict[str, Any]:
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
        if self.logging_config.debug_logs_in_console:
            console: dict[str, Any] = {
                "class": "logging.StreamHandler",
                "level": "DEBUG",
                "formatter": "plain",
                "stream": "ext://sys.stdout",
            }
        else:
            console = {
                "class": "logging.StreamHandler",
                "level": self.loglevel,
                "formatter": "json_traces" if self.logging_config.include_traces else "json",
                "filters": ["app_filter"],
                "stream": "ext://sys.stdout",
            }

        conf: dict[str, Any] = {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "app_filter": {"()": AppFilter},
                "siem_filter": {"()": SiemFilter},
                "public_inspect_filter": {"()": PublicInspectFilter},
            },
            "formatters": {
                "json": {
                    "()": JsonFormatter,
                    "include_traces": False,
                },
                "json_traces": {
                    "()": JsonFormatter,
                    "include_traces": True,
                },
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
                "plain": {
                    "()": PlainTextFormatter,
                },
            },
            "handlers": {
                "console": console,
            },
            "loggers": {
                active_logger_root(): {
                    "handlers": ["console"],
                    "level": self.loglevel,
                    "propagate": False,
                },
                "uvicorn": {
                    "handlers": ["console"],
                    "level": self.loglevel,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": self.loglevel,
                    "propagate": False,
                },
                # Silenced because RequestContextMiddleware logs access itself.
                "uvicorn.access": {
                    "handlers": [],
                    "level": "CRITICAL",
                    "propagate": False,
                },
            },
            "root": {"handlers": ["console"], "level": self.loglevel},
        }

        if self.logging_config.application_id:
            for formatter in conf["formatters"].values():
                if formatter["()"] is JsonFormatter:
                    formatter["application_id"] = self.logging_config.application_id

        self._add_log_handlers(conf)

        return conf

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
