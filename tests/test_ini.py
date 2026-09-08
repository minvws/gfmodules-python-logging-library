from pydantic import BaseModel, field_validator

from gfmodules.logging.ini import split_comma_separated


class TestSplitCommaSeparated:
    def test_splits_a_comma_separated_string(self) -> None:
        validate = split_comma_separated()

        assert validate("app,siem,debug") == ["app", "siem", "debug"]

    def test_strips_whitespace_around_items(self) -> None:
        validate = split_comma_separated()

        assert validate(" app , siem ,debug ") == ["app", "siem", "debug"]

    def test_drops_empty_items(self) -> None:
        validate = split_comma_separated()

        assert validate("app,,siem,") == ["app", "siem"]

    def test_a_single_value_becomes_a_one_item_list(self) -> None:
        validate = split_comma_separated()

        assert validate("debug") == ["debug"]

    def test_an_empty_string_becomes_an_empty_list(self) -> None:
        validate = split_comma_separated()

        assert validate("") == []

    def test_a_non_string_value_passes_through_unchanged(self) -> None:
        validate = split_comma_separated()
        already_a_list = ["app", "siem"]

        assert validate(already_a_list) is already_a_list

    def test_converts_items_through_the_given_item_type(self) -> None:
        validate = split_comma_separated(float)

        assert validate("0.1, 0.2, 0.4") == [0.1, 0.2, 0.4]

    def test_a_non_string_value_skips_item_type_conversion(self) -> None:
        validate = split_comma_separated(float)
        already_converted = [0.1, 0.2]

        assert validate(already_converted) is already_converted


class TestFieldValidatorIntegration:
    def test_wires_into_a_pydantic_model_as_a_before_validator(self) -> None:
        class Config(BaseModel):
            console_streams: list[str] = ["app", "siem"]

            _split_console_streams = field_validator("console_streams", mode="before")(split_comma_separated())

        assert Config.model_validate({"console_streams": "app,debug"}).console_streams == ["app", "debug"]
        assert Config(console_streams=["app", "debug"]).console_streams == ["app", "debug"]
        assert Config().console_streams == ["app", "siem"]

    def test_wires_into_a_pydantic_model_with_a_typed_item_converter(self) -> None:
        class Config(BaseModel):
            retry_backoff: list[float] = [0.1, 0.2]

            _split_retry_backoff = field_validator("retry_backoff", mode="before")(split_comma_separated(float))

        assert Config.model_validate({"retry_backoff": "0.1,0.2,0.4"}).retry_backoff == [0.1, 0.2, 0.4]
