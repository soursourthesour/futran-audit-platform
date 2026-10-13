from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.1.0"


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    file_store: str = "local:./data/files"
    mfa_required: bool = True
    email_mode: str = "outbox"  # outbox | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Futran Audit Platform <no-reply@futransolutions.com>"
    smtp_starttls: bool = True
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-5-5"
    claude_web_search_tool: str = "web_search_20250305"
    data_region_label: str = "us-east"
    session_idle_min: int = 30
    session_max_hours: int = 12
    retention_years_default: int = 7
    virus_scan: str = "off"  # off | clamav
    base_url: str = "http://localhost:8000"
    secret_key: str = "change-me-in-env"
    disable_scheduler: bool = False
    max_upload_mb: int = 50

    @property
    def test_mode(self) -> bool:
        return (not self.mfa_required) or self.email_mode == "outbox"

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
