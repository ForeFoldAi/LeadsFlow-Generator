"""
Application settings — loaded from environment / .env file.
"""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Lead Generation API"
    APP_DESCRIPTION: str = (
        "Multi-source B2B/B2C lead generation engine. "
        "Scrapes 9 sources, deduplicates, scores, and exports leads in LeadsFlow CRM format."
    )
    APP_VERSION: str = "2.0.0"

    # ── Database ───────────────────────────────────────────────────────────────
    # SQLite (default, dev).  Switch to postgresql+asyncpg://... for production.
    DATABASE_URL: str = "sqlite+aiosqlite:///./leads.db"

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["*"]

    # ── API keys ──────────────────────────────────────────────────────────────
    APOLLO_API_KEY: str = ""
    HUNTER_API_KEY: str = ""
    SNOV_CLIENT_ID: str = ""
    SNOV_CLIENT_SECRET: str = ""
    ROCKETREACH_API_KEY: str = ""

    # ── Social credentials ────────────────────────────────────────────────────
    LINKEDIN_EMAIL: str = ""
    LINKEDIN_PASSWORD: str = ""
    FACEBOOK_EMAIL: str = ""
    FACEBOOK_PASSWORD: str = ""
    INSTAGRAM_USERNAME: str = ""
    INSTAGRAM_PASSWORD: str = ""
    TWITTER_USERNAME: str = ""
    TWITTER_PASSWORD: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
