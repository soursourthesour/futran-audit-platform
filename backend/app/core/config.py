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
    refresh_client: str = "anthropic"  # anthropic | fake (demo and browser tests; never calls the network)
    refresh_max_searches: int = 8  # web searches per jurisdiction
    claude_input_usd_per_mtok: float = 3.0  # for the refresh cost log and cap; set to the model's current price
    claude_output_usd_per_mtok: float = 15.0
    claude_search_usd_each: float = 0.01
    data_region_label: str = "us-east"
    session_idle_min: int = 30
    session_max_hours: int = 12
    retention_years_default: int = 7
    virus_scan: str = "off"  # off | clamav
    base_url: str = "http://localhost:8000"
    secret_key: str = "change-me-in-env"
    disable_scheduler: bool = False
    max_upload_mb: int = 50
    trust_proxy_headers: bool = False  # true behind Render/Azure so rate limits see the real client address
    address_autocomplete: str = ""  # photon | google | off; blank means google when a key is set, else photon
    google_places_api_key: str | None = None
    # Email integration (spec §26): Microsoft Graph and Gmail / Directory API. Blank client IDs leave the outbox or SMTP
    # as the only channel. MAIL_PROVIDER_MODE: auto (fake while EMAIL_MODE=outbox, else real), fake, or live.
    mail_provider_mode: str = "auto"
    ms_client_id: str | None = None
    ms_client_secret: str | None = None
    ms_redirect_uri: str | None = None  # default: BASE_URL/api/v1/mail/oauth/microsoft365
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None  # default: BASE_URL/api/v1/mail/oauth/google
    token_encryption_key: str | None = None  # blank: derived from SECRET_KEY
    mail_pace_per_minute: int = 30  # Exchange Online allows 30 messages a minute per mailbox
    mail_bcc_batch_size: int = 450  # Exchange Online allows 500 recipients per message by default
    mail_link_days: int = 14

    @property
    def test_mode(self) -> bool:
        return (not self.mfa_required) or self.email_mode == "outbox"

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
