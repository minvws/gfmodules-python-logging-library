from pydantic import BaseModel, Field


class ConfigLogging(BaseModel):
    # host:port. Unset means console only, with no syslog handlers added.
    syslog_path: str | None = Field(default=None)
    application_id: str | None = Field(default=None)
    include_traces: bool = Field(default=True)
    debug_logs_in_console: bool = Field(default=False)
    correlation_id_expected: bool = Field(default=False)
    # Only enable this where a proxy rewrites X-Forwarded-For; anywhere else the caller might set it.
    trust_forwarded_for: bool = Field(default=False)
