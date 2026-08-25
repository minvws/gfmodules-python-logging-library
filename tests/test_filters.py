import logging

import pytest

from gfmodules.logging.filters import AppFilter, PublicInspectFilter, SiemFilter
from gfmodules.logging.streams import LoggingStreams


def make_record(name: str = "app.service", streams: list[LoggingStreams] | None = None) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name, level=logging.INFO, pathname="", lineno=0, msg="hello", args=(), exc_info=None
    )
    if streams is not None:
        record.stream = streams
    return record


class TestAppFilter:
    @pytest.mark.parametrize("name", ["uvicorn", "uvicorn.error", "app.access"])
    def test_passes_uvicorn_and_access_loggers_without_stream(self, name: str) -> None:
        assert AppFilter().filter(make_record(name=name)) is True

    def test_passes_records_routed_to_app(self) -> None:
        assert AppFilter().filter(make_record(streams=[LoggingStreams.APP])) is True

    def test_rejects_records_not_routed_to_app(self) -> None:
        assert AppFilter().filter(make_record(streams=[LoggingStreams.SIEM])) is False

    def test_rejects_ordinary_records_without_stream(self) -> None:
        assert AppFilter().filter(make_record()) is False


class TestSiemFilter:
    def test_passes_records_routed_to_siem(self) -> None:
        assert SiemFilter().filter(make_record(streams=[LoggingStreams.APP, LoggingStreams.SIEM])) is True

    def test_rejects_records_not_routed_to_siem(self) -> None:
        assert SiemFilter().filter(make_record(streams=[LoggingStreams.APP])) is False

    def test_rejects_records_without_stream(self) -> None:
        assert SiemFilter().filter(make_record(name="uvicorn")) is False


class TestPublicInspectFilter:
    def test_passes_records_routed_to_public_inspect(self) -> None:
        assert PublicInspectFilter().filter(make_record(streams=[LoggingStreams.PUBLIC_INSPECT])) is True

    def test_rejects_records_not_routed_to_public_inspect(self) -> None:
        assert PublicInspectFilter().filter(make_record(streams=[LoggingStreams.APP])) is False
