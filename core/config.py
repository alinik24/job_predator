"""
Central configuration — loads from .env, validates with Pydantic Settings.
All modules import from here; never read os.environ directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM API Configuration ────────────────────────────────────────────────
    llm_api_base_url: str = Field(..., alias="LLM_API_BASE_URL")
    llm_api_key: str = Field(..., alias="LLM_API_KEY")
    llm_api_version: str = Field("2024-01-01", alias="LLM_API_VERSION")
    llm_model_name: str = Field("gpt-4", alias="LLM_MODEL_NAME")
    embedding_model_name: str = Field("text-embedding-3-large", alias="EMBEDDING_MODEL_NAME")

    # ── Optional: Fallback LLM Provider ──────────────────────────────────────
    fallback_llm_api_base_url: Optional[str] = Field(None, alias="FALLBACK_LLM_API_BASE_URL")
    fallback_llm_api_key: Optional[str] = Field(None, alias="FALLBACK_LLM_API_KEY")
    fallback_llm_model_name: Optional[str] = Field(None, alias="FALLBACK_LLM_MODEL_NAME")

    # ── GitHub Token ─────────────────────────────────────────────────────────
    github_token: Optional[str] = Field(None, alias="GITHUB_TOKEN")

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = Field(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/job_predator",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        "postgresql+psycopg2://postgres:postgres@localhost:5432/job_predator",
        alias="DATABASE_URL_SYNC",
    )

    # ── LinkedIn ─────────────────────────────────────────────────────────────
    linkedin_email: Optional[str] = Field(None, alias="LINKEDIN_EMAIL")
    linkedin_password: Optional[str] = Field(None, alias="LINKEDIN_PASSWORD")

    # ── Indeed / StepStone / Xing ────────────────────────────────────────────
    indeed_email: Optional[str] = Field(None, alias="INDEED_EMAIL")
    indeed_password: Optional[str] = Field(None, alias="INDEED_PASSWORD")
    stepstone_email: Optional[str] = Field(None, alias="STEPSTONE_EMAIL")
    stepstone_password: Optional[str] = Field(None, alias="STEPSTONE_PASSWORD")
    xing_email: Optional[str] = Field(None, alias="XING_EMAIL")
    xing_password: Optional[str] = Field(None, alias="XING_PASSWORD")

    # ── Hunter.io (HR email finder) ──────────────────────────────────────────
    hunter_api_key: Optional[str] = Field(None, alias="HUNTER_API_KEY")

    # ── Email outreach ───────────────────────────────────────────────────────
    smtp_host: str = Field("smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(None, alias="SMTP_PASSWORD")
    email_from: Optional[str] = Field(None, alias="EMAIL_FROM")

    # ── Scraping behaviour ───────────────────────────────────────────────────
    scrape_max_results: int = Field(50, alias="SCRAPE_MAX_RESULTS")
    scrape_hours_old: int = Field(72, alias="SCRAPE_HOURS_OLD")
    scrape_proxy: Optional[str] = Field(None, alias="SCRAPE_PROXY")

    # ── Application behaviour ────────────────────────────────────────────────
    # Minimum LLM match score (0-10) to auto-apply; below this → skip
    auto_apply_threshold: float = Field(7.0, alias="AUTO_APPLY_THRESHOLD")
    # Pause for human review before submitting
    human_review: bool = Field(True, alias="HUMAN_REVIEW")
    headless_browser: bool = Field(False, alias="HEADLESS_BROWSER")

    # ── Matching ─────────────────────────────────────────────────────────────
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )

    # ── Paths ─────────────────────────────────────────────────────────────────
    cv_pdf_path: Optional[str] = Field(None, alias="CV_PDF_PATH")
    cv_latex_path: Optional[str] = Field(None, alias="CV_LATEX_PATH")
    documents_dir: str = Field(str(ROOT_DIR / "user_documents"), alias="DOCUMENTS_DIR")
    output_dir: str = Field(str(ROOT_DIR / "output"), alias="OUTPUT_DIR")


# Singleton — import and use `settings` everywhere
settings = Settings()


def get_token_kwargs(model_name: str, n_tokens: int = 2048) -> dict:
    """
    Return the correct token-limit kwarg for a given model.
    Newer models use max_completion_tokens; older models use max_tokens.
    """
    if "gpt-4" in model_name or "gpt-5" in model_name:
        return {"max_completion_tokens": n_tokens}
    return {"max_tokens": n_tokens}
