"""What ``configure()`` registers, so wiring code does not have to thread it
through every library component that logs.
"""

from gfmodules.logging.events import EventCatalogue, validate_catalogue

_catalogue: type[EventCatalogue] | None = None
_access_logs: bool | None = None


def register_catalogue(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> None:
    validate_catalogue(catalogue, access_logs=access_logs)
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


def clear_access_logs() -> None:
    global _access_logs
    _access_logs = None


def active_access_logs() -> bool:
    if _access_logs is None:
        raise RuntimeError(
            "access logging setting unknown: call gfmodules.logging.configure() before adding the middleware"
        )
    return _access_logs
