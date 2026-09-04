from pydantic import BaseModel, Field


class ConfigLogging(BaseModel):
    # host:port. Unset means console only, with no syslog handlers added.
    syslog_path: str | None = Field(default=None)
    application_id: str | None = Field(default=None)
    include_traces: bool = Field(default=True)
    correlation_id_expected: bool = Field(default=False)
    # Whether to include access logs per request.
    access_logs: bool = Field(default=False)
    # Only enable this where a proxy rewrites X-Forwarded-For; anywhere else the caller might set it.
    trust_forwarded_for: bool = Field(default=False)
    # Which streams reach stdout as readable text, from "app", "siem" and "debug".
    # Empty is a choice, not the default: it leaves stdout silent.
    console_streams: list[str] = Field(default=["app", "siem"])
