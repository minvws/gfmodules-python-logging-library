from enum import Enum


class LoggingStreams(Enum):
    """The numbering matches the "stroom" numbering in the logging spec."""

    PUBLIC_INSPECT = 1
    APP = 2
    SIEM = 3
