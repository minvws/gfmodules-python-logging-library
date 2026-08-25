"""The catalogue ``configure()`` registers, so wiring code does not have to
thread one through every library component that logs.
"""

from gfmodules.logging.events import EventCatalogue, validate_catalogue

_catalogue: type[EventCatalogue] | None = None


def register_catalogue(catalogue: type[EventCatalogue]) -> None:
    validate_catalogue(catalogue)
    global _catalogue
    _catalogue = catalogue


def clear_catalogue() -> None:
    global _catalogue
    _catalogue = None


def active_catalogue() -> type[EventCatalogue]:
    if _catalogue is None:
        raise RuntimeError("no event catalogue registered: call gfmodules.logging.configure() during startup")
    return _catalogue


def resolve_catalogue(catalogue: type[EventCatalogue] | None) -> type[EventCatalogue]:
    return catalogue if catalogue is not None else active_catalogue()
