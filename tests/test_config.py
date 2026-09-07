from gfmodules.logging.config import ConfigLogging


def test_defaults_match_the_pre_extraction_behaviour() -> None:
    config = ConfigLogging()

    assert config.syslog_path is None
    assert config.application_id is None
    assert config.include_traces is True
    assert config.console_streams == ["app", "siem"]
    assert config.correlation_id_expected is False


def test_access_logging_is_off_until_an_application_asks_for_it() -> None:
    assert ConfigLogging().access_logs is False


def test_an_empty_console_selection_is_kept_rather_than_read_as_the_default() -> None:
    assert ConfigLogging(console_streams=[]).console_streams == []


def test_accepts_an_application_supplied_configuration() -> None:
    config = ConfigLogging(
        syslog_path="syslog:5514",
        application_id="example-service",
        include_traces=False,
        console_streams=["app", "debug"],
        correlation_id_expected=True,
        access_logs=True,
    )

    assert config.syslog_path == "syslog:5514"
    assert config.application_id == "example-service"
    assert config.include_traces is False
    assert config.console_streams == ["app", "debug"]
    assert config.correlation_id_expected is True
    assert config.access_logs is True
