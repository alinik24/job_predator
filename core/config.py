"""Application configuration from environment variables."""
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (no defaults for security - must be in .env)
    database_url: str
    database_url_sync: str

    # LLM Configuration
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str
    llm_model_name: str = "gpt-4"
    embedding_model_name: str = "text-embedding-3-small"  # 1536 dimensions

    # Optional Azure OpenAI
    azure_openai_endpoint: Optional[str] = None
    azure_openai_key: Optional[str] = None
    azure_openai_deployment: Optional[str] = None
    azure_embedding_deployment: Optional[str] = None

    # Neo4j (no default password for security - must be in .env)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str

    # Application settings
    auto_apply_threshold: float = 7.0
    human_review: bool = True
    headless_browser: bool = False

    # File paths
    cv_pdf_path: str = "./user_documents/cv.pdf"
    cv_latex_path: str = "./user_documents/cv.tex"
    watch_dir: str = "user_documents/inbox"
    archive_dir: str = "user_documents/processed"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env


settings = Settings()
