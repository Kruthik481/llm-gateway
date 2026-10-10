from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Missing or invalid values stop startup (fail fast)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    database_url: str
    redis_url: str
    groq_api_key: str = Field(min_length=1)
    openrouter_api_key: str = Field(min_length=1)
    control_jwt_secret: str = Field(min_length=32)
    metrics_token: str = Field(min_length=16)
    web_origin: str

    groq_base_url: str = "https://api.groq.com/openai/v1"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    rate_limit_per_minute: int = Field(20, ge=1)
    user_daily_tokens: int = Field(50_000, ge=1)
    global_daily_tokens: int = Field(1_000_000, ge=1)
