"""Adapter for applications that populate config models from INI-style files,
where every value is a flat string and there is no native list syntax.

Nothing in this library needs this: ``ConfigLogging`` stays plain ``list[str]``,
agnostic to where its data comes from. An application whose config loader reads
INI opts in per field instead.
"""

from typing import Any, Callable

__all__ = ["split_comma_separated"]


def split_comma_separated(item_type: type[Any] = str) -> Callable[[Any], Any]:
    """Build a pydantic ``mode="before"`` validator that splits a comma-separated
    string into a list, converting each item through `item_type`. Value that
    is not a string (already a list, from a non-INI source, or in a test)
    passes through unchanged.

    Usage:

    ```python
    from gfmodules.logging import ConfigLogging as GFConfigLogging
    from gfmodules.logging.ini import split_comma_separated
    from pydantic import field_validator

    class ConfigLogging(GFConfigLogging):
        _split_console_streams = field_validator("console_streams", mode="before")(
            split_comma_separated()
        )
    ```

    `item_type` converts each stripped piece, for a field that isn't `list[str]`:

    ```python
    _split_retry_backoff = field_validator("retry_backoff", mode="before")(
        split_comma_separated(float)
    )
    ```
    """

    def _validate(value: Any) -> Any:
        if isinstance(value, str):
            return [item_type(item.strip()) for item in value.split(",") if item.strip()]
        return value

    return _validate
