from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./prospector.db"
    portal_username: str = "admin"
    portal_password: str = "demo1234"
    portal_admin_display_name: str = "Lucas Gabriel"
    portal_secret: str = "change-me-in-production"
    portal_session_days: int = 7
    portal_cookie_secure: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-terra"
    deepseek_api_key: str | None = None
    deepseek_api_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    hunter_api_key: str | None = None
    serper_api_key: str | None = None
    outreach_enabled: bool = False
    outreach_webhook_url: str | None = None
    crawler_user_agent: str = "B2BProspector/1.0 (https://github.com/LucasGabrielOM/b2b-technographics-prospector)"
    request_timeout_seconds: float = 12
    discovery_concurrency: int = 8
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
