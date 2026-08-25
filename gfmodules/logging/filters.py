import logging

from gfmodules.logging.loggers import access_logger_name
from gfmodules.logging.streams import LoggingStreams

_UVICORN_LOGGERS = {"uvicorn", "uvicorn.error"}


class AppFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if LoggingStreams.APP in getattr(record, "stream", []):
            return True
        return record.name in _UVICORN_LOGGERS or record.name == access_logger_name()


class PublicInspectFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return LoggingStreams.PUBLIC_INSPECT in getattr(record, "stream", [])


class SiemFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return LoggingStreams.SIEM in getattr(record, "stream", [])
