import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine active environment (defaults to 'dev')
APP_ENV = os.getenv("APP_ENV", "dev").lower()


class Settings(BaseSettings):
    app_env: str = APP_ENV

    redis_host: str
    redis_port: int
    redis_decode_response: bool = True

    # Automatically load the corresponding .env.<env> file
    model_config = SettingsConfigDict(
        env_file=f".env.{APP_ENV}",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore unexpected env vars
    )


# lru_cache ensures the settings are only parsed from disk once
@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
