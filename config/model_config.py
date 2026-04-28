"""
Model Configuration - Provider-agnostic LLM and embedding configuration
Supports: Azure OpenAI, OpenAI, Ollama, LiteLLM, and custom endpoints

Environment variables:
    # Azure OpenAI (default)
    AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
    AZURE_OPENAI_KEY=your-key
    AZURE_OPENAI_DEPLOYMENT=gpt-4o  # or gpt-4, gpt-4-turbo
    AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large

    # OpenAI
    OPENAI_API_KEY=sk-...
    OPENAI_MODEL=gpt-4o

    # Ollama (local)
    OLLAMA_BASE_URL=http://localhost:11434
    OLLAMA_MODEL=llama3.1:8b

    # Custom
    CUSTOM_API_BASE=https://your-endpoint.com
    CUSTOM_API_KEY=your-key
    CUSTOM_MODEL=your-model
"""
from __future__ import annotations

import os
from typing import Optional, Dict, Any, Literal
from dataclasses import dataclass
from loguru import logger


ProviderType = Literal["azure", "openai", "ollama", "litellm", "custom"]


@dataclass
class ModelConfig:
    """LLM and embedding model configuration"""

    # Provider
    provider: ProviderType = "azure"

    # LLM settings
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000

    # Embedding settings
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072

    # API credentials
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    api_version: str = "2024-02-15-preview"

    # Azure-specific
    azure_deployment: Optional[str] = None
    azure_embedding_deployment: Optional[str] = None

    def __post_init__(self):
        """Load from environment variables if not provided"""
        if self.provider == "azure":
            self.api_key = self.api_key or os.getenv("AZURE_OPENAI_KEY")
            self.api_base = self.api_base or os.getenv("AZURE_OPENAI_ENDPOINT")
            self.azure_deployment = self.azure_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
            self.azure_embedding_deployment = self.azure_embedding_deployment or os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
            self.llm_model = self.azure_deployment
            self.embedding_model = self.azure_embedding_deployment

        elif self.provider == "openai":
            self.api_key = self.api_key or os.getenv("OPENAI_API_KEY")
            self.llm_model = self.llm_model or os.getenv("OPENAI_MODEL", "gpt-4o")
            self.embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

        elif self.provider == "ollama":
            self.api_base = self.api_base or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self.llm_model = self.llm_model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
            self.embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

        elif self.provider == "custom":
            self.api_key = self.api_key or os.getenv("CUSTOM_API_KEY")
            self.api_base = self.api_base or os.getenv("CUSTOM_API_BASE")
            self.llm_model = self.llm_model or os.getenv("CUSTOM_MODEL", "gpt-4o")

    def get_llm_client(self) -> Any:
        """Get LLM client based on provider"""
        if self.provider == "azure":
            from openai import AzureOpenAI
            return AzureOpenAI(
                api_key=self.api_key,
                api_version=self.api_version,
                azure_endpoint=self.api_base,
            )

        elif self.provider == "openai":
            from openai import OpenAI
            return OpenAI(api_key=self.api_key)

        elif self.provider == "ollama":
            from openai import OpenAI
            return OpenAI(
                base_url=self.api_base,
                api_key="ollama",  # Ollama doesn't need real key
            )

        elif self.provider in ["litellm", "custom"]:
            from openai import OpenAI
            return OpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )

        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def get_embedding_client(self) -> Any:
        """Get embedding client (same as LLM client for most providers)"""
        return self.get_llm_client()

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as dict"""
        return {
            "provider": self.provider,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "api_base": self.api_base,
        }


# Global config instance
_config: Optional[ModelConfig] = None


def get_model_config() -> ModelConfig:
    """Get or create global model configuration"""
    global _config
    if _config is None:
        _config = ModelConfig()
        logger.info(f"Model config initialized: {_config.to_dict()}")
    return _config


def set_model_config(config: ModelConfig):
    """Set global model configuration"""
    global _config
    _config = config
    logger.info(f"Model config updated: {_config.to_dict()}")


# Convenience functions
def get_llm_client():
    """Get LLM client using global config"""
    return get_model_config().get_llm_client()


def get_embedding_client():
    """Get embedding client using global config"""
    return get_model_config().get_embedding_client()
