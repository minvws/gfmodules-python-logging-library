import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import pytest

from gfmodules.logging.event_overview import main, render_event_overview
from gfmodules.logging.events import EventCatalogue, LogEvent
from gfmodules.logging.streams import LoggingStreams
from gfmodules.logging.testing import assert_event_overview_current

APP = LoggingStreams.APP
SIEM = LoggingStreams.SIEM


class Catalogue(EventCatalogue):
    RESOURCE_CREATED = LogEvent(
        "100700",
        logging.INFO,
        (APP, SIEM),
        {APP: ("resource_id", "owner_id"), SIEM: ("resource_id",)},
    )
    LOOKUP_REJECTED = LogEvent("100702", logging.WARNING, (APP,), {APP: ("error_reason",)})
    ACCESS_REQUEST = LogEvent("100", logging.INFO, (APP,), {APP: ("status_code",)})

    access_event_id: ClassVar[Mapping[tuple[str, str], str]] = {("POST", "/resources"): "100710"}


class UnroutedCatalogue(EventCatalogue):
    DEBUG_DUMP = LogEvent("100800", logging.DEBUG, (APP, SIEM))
    AUDIT_ONLY = LogEvent("100801", logging.INFO, (APP, SIEM), {APP: ("detail",)})


OVERVIEW = """\
# Log events

<!-- markdownlint-disable MD013 -->

Generated from `tests.test_event_overview:Catalogue` by `gfmodules.logging.event_overview`.
Do not edit by hand.

Each stream lists the events that reach it and the fields they carry there besides the context fields.
*any* means the event has no allow-list, so every field it is logged with reaches the stream.
*none* means the event carries only the context fields there.

## Context fields

Every event carries these on every stream, whenever the request context holds a value for them.

- `request_id`
- `ip`
- `user_agent`
- `client_trace_id`
- `correlation_id`
- `endpoint`
- `method`
- `scope`

## Stream `app`

| Event | Id | Level | Fields |
| --- | --- | --- | --- |
| `RESOURCE_CREATED` | 100700 | INFO | `resource_id`, `owner_id` |
| `LOOKUP_REJECTED` | 100702 | WARNING | `error_reason` |
| `ACCESS_REQUEST` | 100 | INFO | `status_code` |

## Stream `siem`

| Event | Id | Level | Fields |
| --- | --- | --- | --- |
| `RESOURCE_CREATED` | 100700 | INFO | `resource_id` |

## Access event ids per route

`ACCESS_REQUEST` carries these ids instead of its own on these routes.

| Method | Route | Id |
| --- | --- | --- |
| POST | `/resources` | 100710 |
"""


class TestRenderEventOverview:
    def test_lists_each_streams_events_with_their_fields(self) -> None:
        assert render_event_overview(Catalogue) == OVERVIEW

    def test_an_event_without_an_allow_list_carries_any_field(self) -> None:
        overview = render_event_overview(UnroutedCatalogue)

        assert "| `DEBUG_DUMP` | 100800 | DEBUG | *any* |" in overview

    def test_a_stream_the_allow_list_leaves_out_carries_only_the_context(self) -> None:
        overview = render_event_overview(UnroutedCatalogue)

        assert "| `AUDIT_ONLY` | 100801 | INFO | *none* |" in overview

    def test_without_access_logs_the_access_event_is_left_out(self) -> None:
        overview = render_event_overview(Catalogue, access_logs=False)

        assert "ACCESS_REQUEST" not in overview
        assert "/resources" not in overview
        assert "| `RESOURCE_CREATED` | 100700 | INFO | `resource_id`, `owner_id` |" in overview


class TestCommandLine:
    def test_prints_the_overview_of_the_named_catalogue(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["tests.test_event_overview:Catalogue"])

        assert capsys.readouterr().out == OVERVIEW

    def test_leaves_the_access_event_out_on_request(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["tests.test_event_overview:Catalogue", "--no-access-logs"])

        assert capsys.readouterr().out == render_event_overview(Catalogue, access_logs=False)

    def test_rejects_a_name_that_is_not_a_catalogue(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            main(["tests.test_event_overview:OVERVIEW"])

        assert "tests.test_event_overview:OVERVIEW names no event catalogue" in capsys.readouterr().err


class TestAssertEventOverviewCurrent:
    def test_passes_when_the_file_matches_the_catalogue(self, tmp_path: Path) -> None:
        path = tmp_path / "events.md"
        path.write_text(OVERVIEW, encoding="utf-8")

        assert_event_overview_current(Catalogue, path)

    def test_names_the_command_that_regenerates_a_stale_file(self, tmp_path: Path) -> None:
        path = tmp_path / "events.md"
        path.write_text(OVERVIEW.replace("`owner_id`", "`created_by`"), encoding="utf-8")

        command = f"python -m gfmodules.logging.event_overview tests.test_event_overview:Catalogue > {path}"
        with pytest.raises(AssertionError, match=re.escape(command)):
            assert_event_overview_current(Catalogue, path)

    def test_fails_on_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(AssertionError, match="does not match"):
            assert_event_overview_current(Catalogue, tmp_path / "events.md")

    def test_regenerates_without_access_logs_when_the_check_leaves_them_out(self, tmp_path: Path) -> None:
        path = tmp_path / "events.md"
        path.write_text(OVERVIEW, encoding="utf-8")

        with pytest.raises(AssertionError, match=re.escape("tests.test_event_overview:Catalogue --no-access-logs > ")):
            assert_event_overview_current(Catalogue, path, access_logs=False)
