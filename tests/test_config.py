from gfmodules.logging.config import ConfigLogging


def test_defaults_match_the_pre_extraction_behaviour() -> None:
    config = ConfigLogging()

    assert config.syslog_path is None
    assert config.application_id is None
    assert config.include_traces is True
    assert config.debug_logs_in_console is False
    assert config.correlation_id_expected is False


def test_access_logging_is_off_until_an_application_asks_for_it() -> None:
    assert ConfigLogging().access_logs is False


def test_accepts_an_application_supplied_configuration() -> None:
    config = ConfigLogging(
        syslog_path="syslog:5514",
        application_id="example-service",
        include_traces=False,
        debug_logs_in_console=True,
        correlation_id_expected=True,
        access_logs=True,
    )

    assert config.syslog_path == "syslog:5514"
    assert config.application_id == "example-service"
    assert config.include_traces is False
    assert config.debug_logs_in_console is True
    assert config.correlation_id_expected is True
    assert config.access_logs is True
