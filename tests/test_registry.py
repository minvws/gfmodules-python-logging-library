import pytest

from gfmodules.logging import configure
from gfmodules.logging.config import ConfigLogging
from gfmodules.logging.registry import active_access_logs, register_access_logs, registered_config
from tests.helpers.catalogue import CompleteCatalogue


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


class TestConfig:
    def test_falls_back_to_the_defaults_until_configure_registers_one(self) -> None:
        assert registered_config() == ConfigLogging()

    def test_configure_registers_the_configuration_it_was_given(self) -> None:
        config = ConfigLogging(console_streams=[], correlation_id_expected=True, trust_forwarded_for=True)

        configure(config=config, loglevel="INFO", catalogue=CompleteCatalogue)

        assert registered_config() is config
