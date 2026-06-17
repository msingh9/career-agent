from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "us"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    search_titles: str = "VP,Senior Director,Director"
    search_keywords: str = (
        "semiconductor,semiconductors,chip,fab,ASIC,foundry,wafer,EDA,GPU,CPU"
    )
    search_locations: str = ""


def get_settings() -> Settings:
    load_dotenv(ENV_FILE, override=True)
    return Settings()


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
