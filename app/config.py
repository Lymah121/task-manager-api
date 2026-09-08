from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://app:app@localhost:5433/taskmanager"
    test_database_url: str = "postgresql+psycopg://app:app@localhost:5433/taskmanager_test"

    # Deliberately no default: a fallback dev secret is exactly the kind of
    # thing that reaches production. Missing JWT_SECRET must fail at import.
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
