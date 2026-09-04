"""Formatter output tests.

The rendered record is a fixed contract with the log server, so these compare
the formatted string itself rather than the parsed structure.
"""

import json
import logging
import re
from typing import Any

import pytest

from gfmodules.logging.context import ContextField, bind_context, register_context_fields
from gfmodules.logging.formatter import JsonFormatter, PlainTextFormatter
from gfmodules.logging.streams import LoggingStreams

CREATED = 1776000000.5
FIELD_STREAMS = {
    LoggingStreams.APP: ("component", "status", "error_detail"),
    LoggingStreams.SIEM: ("component", "status"),
}
EXTRAS = {
    "component": "database",
    "status": "unhealthy",
    "error_detail": "connection refused",
    "secret_field": "must-not-reach-siem",
}
BOUND_CONTEXT = {
    "request_id": "req-1",
    "ip": "10.0.0.7",
    "client_trace_id": "trace-1",
    "correlation_id": "corr-1",
    "endpoint": "/health",
    "method": "GET",
    "tenant_id": "t-1",
}

# Traceback frame lines are stdlib output carrying absolute paths; blank them so
# the comparison is machine-independent. Matches raw and JSON-escaped output.
_FRAME = re.compile(r'File \\?"[^"]*", line \d+, in [\w<>.]+')


def normalize(text: str) -> str:
    return _FRAME.sub("File <frame>, line 0, in <frame>", text)


def make_record(*, with_exc: bool = False, with_field_streams: bool = True) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.health",
        level=logging.ERROR,
        pathname="/srv/app/health.py",
        lineno=42,
        msg="Component %s is unhealthy",
        args=("database",),
        exc_info=None,
    )
    record.created = CREATED
    record.module = "health"
    record.event_id = "100600"
    record.stream = [LoggingStreams.APP, LoggingStreams.SIEM]
    if with_field_streams:
        record.field_streams = FIELD_STREAMS
    for key, value in EXTRAS.items():
        setattr(record, key, value)
    if with_exc:
        try:
            # The traceback renders this source line, so the statement has to
            # stay textually identical to the one in TRACEBACK.
            raise ValueError("boom")
        except ValueError as exc:
            record.exc_info = (type(exc), exc, exc.__traceback__)
    return record


@pytest.fixture(autouse=True)
def declare_tenant_id() -> Any:
    register_context_fields((ContextField(name="tenant_id", header="X-Tenant-Id"),))
    yield
    register_context_fields(())


def format_case(formatter: logging.Formatter, **kwargs: Any) -> str:
    with bind_context(BOUND_CONTEXT):
        return normalize(formatter.format(make_record(**kwargs)))


APP_ID = "example-service"

TRACEBACK = (
    "Traceback (most recent call last):\n"
    "  File <frame>, line 0, in <frame>\n"
    '    raise ValueError("boom")\n'
    "ValueError: boom"
)

UNROUTED_MESSAGE: dict[str, Any] = {
    "request_id": "req-1",
    "ip": "10.0.0.7",
    "client_trace_id": "trace-1",
    "correlation_id": "corr-1",
    "endpoint": "/health",
    "method": "GET",
    "tenant_id": "t-1",
    "component": "database",
    "status": "unhealthy",
    "error_detail": "connection refused",
    "secret_field": "must-not-reach-siem",
}

APP_MESSAGE: dict[str, Any] = {
    "request_id": "req-1",
    "ip": "10.0.0.7",
    "client_trace_id": "trace-1",
    "correlation_id": "corr-1",
    "component": "database",
    "status": "unhealthy",
    "error_detail": "connection refused",
}

SIEM_MESSAGE: dict[str, Any] = {
    "request_id": "req-1",
    "ip": "10.0.0.7",
    "client_trace_id": "trace-1",
    "correlation_id": "corr-1",
    "component": "database",
    "status": "unhealthy",
}


def expected_record(
    message: dict[str, Any], *, application_id: str | None = APP_ID, stream_id: str | None = None
) -> str:
    """The exact JSON a record must render to.

    The keys are written in the order the log server has to receive them, so
    comparing the dumped string pins the order as well as the content.
    """
    record: dict[str, Any] = {
        "event_id": "100600",
        "timestamp": "2026-04-12T13:20:00.500000+00:00",
        "level": "ERROR",
        "event_description": "Component database is unhealthy",
        "source": "health:42",
    }
    if application_id is not None:
        record["application_id"] = application_id
    if stream_id is not None:
        record["stream_id"] = stream_id
    record["message"] = message
    return json.dumps(record)


PLAIN_LINE = (
    "2026-04-12T13:20:00Z ERROR    app.health [100600] Component database is unhealthy "
    "request_id=req-1 ip=10.0.0.7 client_trace_id=trace-1 correlation_id=corr-1 "
    "endpoint=/health method=GET tenant_id=t-1 "
    "component=database status=unhealthy error_detail=connection refused "
    "secret_field=must-not-reach-siem"
)

PLAIN_APP_LINE = (
    "2026-04-12T13:20:00Z ERROR    app.health [100600] Component database is unhealthy "
    "request_id=req-1 ip=10.0.0.7 client_trace_id=trace-1 correlation_id=corr-1 "
    "component=database status=unhealthy error_detail=connection refused"
)

JSON_CASES: dict[str, tuple[JsonFormatter, dict[str, Any], str]] = {
    "console": (
        JsonFormatter(include_traces=False, application_id=APP_ID),
        {},
        expected_record(UNROUTED_MESSAGE),
    ),
    "traces": (
        JsonFormatter(include_traces=True, application_id=APP_ID),
        {"with_exc": True},
        expected_record({"exception": TRACEBACK, **UNROUTED_MESSAGE}),
    ),
    "app_stream": (
        JsonFormatter(include_traces=False, stream=LoggingStreams.APP, stream_id="app", application_id=APP_ID),
        {},
        expected_record(APP_MESSAGE, stream_id="app"),
    ),
    "siem_stream": (
        JsonFormatter(include_traces=False, stream=LoggingStreams.SIEM, stream_id="siem", application_id=APP_ID),
        {},
        expected_record(SIEM_MESSAGE, stream_id="siem"),
    ),
    "public_inspect_stream": (
        JsonFormatter(include_traces=False, stream_id="public_inspect", application_id=APP_ID),
        {},
        expected_record(UNROUTED_MESSAGE, stream_id="public_inspect"),
    ),
    "debug_stream": (
        JsonFormatter(include_traces=True, stream_id="debug", application_id=APP_ID),
        {"with_exc": True},
        expected_record({"exception": TRACEBACK, **UNROUTED_MESSAGE}, stream_id="debug"),
    ),
    "no_application_id": (
        JsonFormatter(include_traces=False),
        {},
        expected_record(UNROUTED_MESSAGE, application_id=None),
    ),
    "no_field_streams": (
        JsonFormatter(include_traces=False, stream=LoggingStreams.SIEM, stream_id="siem", application_id=APP_ID),
        {"with_field_streams": False},
        expected_record(UNROUTED_MESSAGE, stream_id="siem"),
    ),
}

PLAIN_APP_LINE_WITH_TAG = (
    "2026-04-12T13:20:00Z [app] ERROR    app.health [100600] Component database is unhealthy "
    "request_id=req-1 ip=10.0.0.7 client_trace_id=trace-1 correlation_id=corr-1 "
    "component=database status=unhealthy error_detail=connection refused"
)

PLAIN_CASES: dict[str, tuple[PlainTextFormatter, dict[str, Any], str]] = {
    "unrouted": (PlainTextFormatter(), {}, PLAIN_LINE),
    "with_exc": (PlainTextFormatter(), {"with_exc": True}, f"{PLAIN_LINE}\n{TRACEBACK}"),
    "app_stream": (PlainTextFormatter(stream=LoggingStreams.APP, stream_id="app"), {}, PLAIN_APP_LINE_WITH_TAG),
}


@pytest.mark.parametrize("case", sorted(JSON_CASES))
def test_json_output_matches_the_expected_record(case: str) -> None:
    formatter, kwargs, expected = JSON_CASES[case]

    assert format_case(formatter, **kwargs) == expected


@pytest.mark.parametrize("case", sorted(PLAIN_CASES))
def test_plain_output_matches_the_expected_line(case: str) -> None:
    formatter, kwargs, expected = PLAIN_CASES[case]

    assert format_case(formatter, **kwargs) == expected


class TestStreamRouting:
    """The allow-list is what keeps data out of the SIEM stream."""

    def siem_message(self, **kwargs: Any) -> dict[str, Any]:
        formatter = JsonFormatter(include_traces=False, stream=LoggingStreams.SIEM, stream_id="siem")
        return dict(json.loads(format_case(formatter, **kwargs))["message"])

    def app_message(self) -> dict[str, Any]:
        formatter = JsonFormatter(include_traces=False, stream=LoggingStreams.APP, stream_id="app")
        return dict(json.loads(format_case(formatter))["message"])

    def test_a_field_allowed_for_app_only_is_absent_from_siem(self) -> None:
        assert self.app_message()["error_detail"] == "connection refused"
        assert "error_detail" not in self.siem_message()

    def test_a_field_on_no_allow_list_reaches_neither_stream(self) -> None:
        assert "secret_field" not in self.app_message()
        assert "secret_field" not in self.siem_message()

    def test_correlation_metadata_survives_routing_on_every_stream(self) -> None:
        for message in (self.app_message(), self.siem_message()):
            assert message["request_id"] == "req-1"
            assert message["ip"] == "10.0.0.7"
            assert message["client_trace_id"] == "trace-1"
            assert message["correlation_id"] == "corr-1"

    def test_endpoint_and_method_are_dropped_when_not_allow_listed(self) -> None:
        assert "endpoint" not in self.siem_message()
        assert "method" not in self.siem_message()

    def test_routing_is_skipped_when_the_event_declares_no_field_streams(self) -> None:
        message = self.siem_message(with_field_streams=False)

        assert message["error_detail"] == "connection refused"
        assert message["secret_field"] == "must-not-reach-siem"


class TestMessageSanitisation:
    def test_control_characters_are_stripped_from_the_description(self) -> None:
        record = make_record()
        record.msg = "line\x00one\x1fbreak\x7f"
        record.args = ()

        out = json.loads(JsonFormatter(include_traces=False).format(record))

        assert out["event_description"] == "lineonebreak"

    def test_records_without_an_event_id_report_none(self) -> None:
        record = make_record()
        del record.event_id  # type: ignore[attr-defined]

        assert json.loads(JsonFormatter(include_traces=False).format(record))["event_id"] is None

    def test_plain_output_reports_a_dash_for_records_without_an_event_id(self) -> None:
        record = make_record()
        del record.event_id  # type: ignore[attr-defined]

        assert "[-]" in PlainTextFormatter().format(record)


class TestTraceInclusion:
    def test_traces_are_omitted_when_disabled(self) -> None:
        out = json.loads(format_case(JsonFormatter(include_traces=False), with_exc=True))

        assert "exception" not in out["message"]

    def test_stack_info_is_included_when_traces_are_enabled(self) -> None:
        record = make_record()
        record.stack_info = "Stack (most recent call last):\n  ..."

        out = json.loads(JsonFormatter(include_traces=True).format(record))

        assert out["message"]["stack_info"].startswith("Stack (most recent call last):")

    def test_plain_output_keeps_the_traceback_by_default(self) -> None:
        assert format_case(PlainTextFormatter(), with_exc=True) == f"{PLAIN_LINE}\n{TRACEBACK}"

    def test_plain_output_omits_the_traceback_when_traces_are_disabled(self) -> None:
        assert format_case(PlainTextFormatter(include_traces=False), with_exc=True) == PLAIN_LINE

    def test_non_serialisable_values_fall_back_to_their_string_form(self) -> None:
        record = make_record()
        record.thing = object()

        out = json.loads(JsonFormatter(include_traces=False).format(record))

        assert out["message"]["thing"].startswith("<object object at")
