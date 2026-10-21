from collections import Counter

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class ConfigLogging(BaseModel):
    # host:port. Unset means console only, with no syslog handlers added.
    syslog_path: str | None = Field(default=None)
    application_id: str | None = Field(default=None)
    include_traces: bool = Field(default=True)
    correlation_id_expected: bool = Field(default=False)
    # Whether to include access logs per request.
    access_logs: bool = Field(default=True)
    # Only enable this where a proxy rewrites X-Forwarded-For; anywhere else the caller might set it.
    trust_forwarded_for: bool = Field(default=False)
    # Which streams reach stdout as readable text, from "app", "siem" and "debug".
    # Empty leaves stdout silent.
    console_streams: list[str] = Field(default=["app", "siem"])
    syslog_streams: list[str] = Field(default=["app", "siem", "public_inspect"])

    @field_validator("console_streams", "syslog_streams")
    @classmethod
    def _reject_duplicate_streams(cls, names: list[str], info: ValidationInfo) -> list[str]:
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            raise ValueError(f"duplicate {info.field_name} {duplicates}")
        return names
