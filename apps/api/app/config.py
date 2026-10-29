from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DISCIPLINE_")

    database_path: str = "/data/discipline.db"
    log_level: str = "INFO"
    # Cookie только по HTTPS. Отключать лишь для локальной разработки по http.
    cookie_secure: bool = True
    session_days: int = 30
    bootstrap_token_hours: int = 24
    invitation_hours: int = 48
    login_window_minutes: int = 15
    login_max_failures: int = 5
    scheduler_interval_seconds: int = 30
    scheduler_enabled: bool = True

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
