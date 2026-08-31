import pytest

from gfmodules.logging.registry import active_access_logs, register_access_logs


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
