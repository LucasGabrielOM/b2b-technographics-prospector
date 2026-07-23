from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./prospector.db"
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
