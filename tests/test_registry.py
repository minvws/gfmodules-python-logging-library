import pytest

from gfmodules.logging import configure
from gfmodules.logging.config import ConfigLogging
from gfmodules.logging.events import EventCatalogue, validate_catalogue
from gfmodules.logging.registry import active_access_logs, active_catalogue, register_access_logs
from tests.helpers.catalogue import CompleteCatalogue, IncompleteCatalogue


class TestAccessLogsSetting:
    def test_is_unknown_until_configure_registers_it(self) -> None:
        with pytest.raises(RuntimeError, match="access logging"):
            active_access_logs()

    def test_reports_what_was_registered(self) -> None:
        register_access_logs(True)

        assert active_access_logs() is True

    def test_reports_an_application_that_asked_for_none(self) -> None:
        register_access_logs(False)

        assert active_access_logs() is False


class TestConfigure:
    def test_validates_the_catalogue_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[type[EventCatalogue]] = []

        def counting(catalogue: type[EventCatalogue], *, access_logs: bool = True) -> None:
            calls.append(catalogue)
            validate_catalogue(catalogue, access_logs=access_logs)

        monkeypatch.setattr("gfmodules.logging.validate_catalogue", counting)
        monkeypatch.setattr("gfmodules.logging.registry.validate_catalogue", counting)

        configure(config=ConfigLogging(console_streams=[]), loglevel="INFO", catalogue=CompleteCatalogue)

        assert calls == [CompleteCatalogue]

    def test_an_invalid_catalogue_registers_nothing(self) -> None:
        with pytest.raises(ValueError, match="does not define required events"):
            configure(config=ConfigLogging(), loglevel="INFO", catalogue=IncompleteCatalogue)

        with pytest.raises(RuntimeError, match="no event catalogue registered"):
            active_catalogue()
        with pytest.raises(RuntimeError, match="access logging setting unknown"):
            active_access_logs()
