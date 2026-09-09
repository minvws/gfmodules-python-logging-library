from pydantic import BaseModel, Field

from gfmodules.logging import ConfigLogging


class AppSettings(BaseModel):
    version: str = "1.4.0"
    loglevel: str = "info"


class Settings(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    logging: ConfigLogging = Field(
        default_factory=lambda: ConfigLogging(
            # In a deployment this is the log server, "syslog.internal:5514".
            syslog_path=None,
            application_id="example-service",
            correlation_id_expected=True,
        )
    )
