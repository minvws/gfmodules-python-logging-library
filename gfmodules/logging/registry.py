"""What ``configure()`` registers, so wiring code does not have to thread it
through every library component that logs.
"""

from gfmodules.logging.events import EventCatalogue, validate_catalogue

_catalogue: type[EventCatalogue] | None = None
_access_logs = False


def register_catalogue(catalogue: type[EventCatalogue]) -> None:
    validate_catalogue(catalogue, access_logs=access_logs_enabled())
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


def register_access_logs(enabled: bool) -> None:
    global _access_logs
    _access_logs = enabled


def access_logs_enabled() -> bool:
    return _access_logs
