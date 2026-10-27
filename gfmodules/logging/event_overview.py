import argparse
import importlib
import logging
import sys
from collections.abc import Iterable, Sequence

from gfmodules.logging.context import STANDARD_FIELDS
from gfmodules.logging.events import EventCatalogue, LogEvent, _excused_events, declared_events
from gfmodules.logging.streams import LoggingStreams

_LEGEND = """\
Each stream lists the events that reach it and the fields they carry there besides the context fields.
*any* means the event has no allow-list, so every field it is logged with reaches the stream.
*none* means the event carries only the context fields there."""

_CONTEXT_INTRO = "Every event carries these on every stream, whenever the request context holds a value for them."

_ACCESS_INTRO = "`ACCESS_REQUEST` carries these ids instead of its own on these routes."


def _catalogue_name(catalogue: type[EventCatalogue]) -> str:
    return f"{catalogue.__module__}:{catalogue.__qualname__}"


def overview_command(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> str:
    flag = "" if access_logs else " --no-access-logs"
    return f"python -m {__spec__.name} {_catalogue_name(catalogue)}{flag}"


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    lines = [header, ["---"] * len(header), *rows]
    return "\n".join(f"| {' | '.join(cells)} |" for cells in lines)


def _section(title: str, *paragraphs: str) -> str:
    return "\n\n".join((f"## {title}", *paragraphs))


def _fields_on(event: LogEvent, stream: LoggingStreams) -> str:
    if not event.fields:
        return "*any*"
    return ", ".join(f"`{name}`" for name in event.fields.get(stream, ())) or "*none*"


def _stream_section(stream: LoggingStreams, events: Sequence[tuple[str, LogEvent]]) -> str:
    rows = [
        (f"`{name}`", event.event_id, logging.getLevelName(event.level), _fields_on(event, stream))
        for name, event in events
    ]
    return _section(f"Stream `{stream.name.lower()}`", _table(("Event", "Id", "Level", "Fields"), rows))


def _access_section(catalogue: type[EventCatalogue]) -> str:
    rows = [(method, f"`{route}`", event_id) for (method, route), event_id in catalogue.access_event_id.items()]
    return _section("Access event ids per route", _ACCESS_INTRO, _table(("Method", "Route", "Id"), rows))


def render_event_overview(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> str:
    excused = _excused_events(access_logs)
    events = [(name, event) for name, event in declared_events(catalogue) if name not in excused]
    header = "\n\n".join(
        (
            "# Log events",
            "<!-- markdownlint-disable MD013 -->",
            f"Generated from `{_catalogue_name(catalogue)}` by `{__spec__.name}`.\nDo not edit by hand.",
            _LEGEND,
        )
    )
    context = _section("Context fields", _CONTEXT_INTRO, "\n".join(f"- `{field.name}`" for field in STANDARD_FIELDS))
    reaching = {
        stream: [(name, event) for name, event in events if stream in event.streams] for stream in LoggingStreams
    }
    streams = [_stream_section(stream, reached) for stream, reached in reaching.items() if reached]
    access = [_access_section(catalogue)] if access_logs and catalogue.access_event_id else []
    return "\n\n".join((header, context, *streams, *access)) + "\n"


def _load_catalogue(name: str) -> type[EventCatalogue]:
    module_name, _, attribute = name.partition(":")
    catalogue = getattr(importlib.import_module(module_name), attribute, None)
    if not (isinstance(catalogue, type) and issubclass(catalogue, EventCatalogue)):
        raise argparse.ArgumentTypeError(f"{name} names no event catalogue")
    return catalogue


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog=f"python -m {__spec__.name}",
        description="Print the markdown overview of the events an event catalogue declares.",
    )
    parser.add_argument("catalogue", type=_load_catalogue, help="the catalogue as module:Class")
    parser.add_argument(
        "--no-access-logs",
        dest="access_logs",
        action="store_false",
        help="leave the access events out, for an application that runs with access_logs off",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(render_event_overview(args.catalogue, access_logs=args.access_logs))


if __name__ == "__main__":
    main()
