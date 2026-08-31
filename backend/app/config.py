# Copyright 2026 Manish Singh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
    # General agentic work (chat, fit, materials, summaries) — keep cheap/fast.
    openai_model: str = "gpt-4o-mini"
    # Resume digestion only — a stronger model, run once per resume upload.
    openai_digest_model: str = "gpt-5.2"

    search_titles: str = "VP,Senior Director,Director"
    search_keywords: str = (
        "semiconductor,semiconductors,chip,fab,ASIC,foundry,wafer,EDA,GPU,CPU"
    )
    search_locations: str = ""

    # When set, auto-apply drives your real Chrome over the DevTools Protocol
    # (Chrome must be running with remote debugging enabled) instead of
    # launching a throwaway Chromium. This reuses your logged-in sessions.
    # Example: http://127.0.0.1:9222
    chrome_cdp_url: str = ""


def get_settings() -> Settings:
    load_dotenv(ENV_FILE, override=True)
    return Settings()


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
