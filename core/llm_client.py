"""
LLM Client Wrapper
==================
Unified interface for multiple LLM providers (OpenAI, Azure, Claude, OpenRouter, etc.)
Automatically routes to the correct provider based on configuration.
"""

from typing import Optional, Dict, Any, List
from openai import AzureOpenAI, OpenAI
from loguru import logger

from core.config import settings


class LLMClient:
    """
    Universal LLM client that works with any OpenAI-compatible API.

    Supports:
    - OpenAI API (api.openai.com)
    - Azure OpenAI
    - OpenRouter (openrouter.ai)
    - Claude via OpenRouter
    - Any OpenAI-compatible endpoint
    """

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        """
        Initialize LLM client.

        Args:
            api_base: API endpoint URL (defaults to settings.llm_api_base_url)
            api_key: API key (defaults to settings.llm_api_key)
            api_version: API version (defaults to settings.llm_api_version)
            model_name: Model to use (defaults to settings.llm_model_name)
        """
        self.api_base = api_base or settings.llm_api_base_url
        self.api_key = api_key or settings.llm_api_key
        self.api_version = api_version or settings.llm_api_version
        self.model_name = model_name or settings.llm_model_name

        # Detect provider type from API base URL
        self.provider = self._detect_provider(self.api_base)

        # Initialize appropriate client
        self.client = self._create_client()

        logger.info(f"LLM Client initialized: provider={self.provider}, model={self.model_name}")

    def _detect_provider(self, api_base: str) -> str:
        """Detect provider from API base URL"""
        api_base_lower = api_base.lower()

        if "azure" in api_base_lower or "openai.azure.com" in api_base_lower:
            return "azure"
        elif "openrouter" in api_base_lower:
            return "openrouter"
        elif "anthropic" in api_base_lower or "claude" in api_base_lower:
            return "anthropic"
        elif "api.openai.com" in api_base_lower:
            return "openai"
        else:
            # Default to OpenAI-compatible
            return "openai-compatible"

    def _create_client(self):
        """Create the appropriate client based on provider"""
        if self.provider == "azure":
            # Azure OpenAI requires special client
            return AzureOpenAI(
                azure_endpoint=self.api_base,
                api_key=self.api_key,
                api_version=self.api_version
            )
        else:
            # OpenAI, OpenRouter, and compatible APIs use standard client
            return OpenAI(
                base_url=self.api_base,
                api_key=self.api_key
            )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
        **kwargs
    ) -> Any:
        """
        Create chat completion (unified interface).

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            response_format: Response format (e.g., {"type": "json_object"})
            **kwargs: Additional provider-specific parameters

        Returns:
            Completion response object
        """
        params = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }

        # Add optional parameters
        if max_tokens:
            # Handle different parameter names for different providers
            if self.provider == "azure" or "gpt-4" in self.model_name or "gpt-5" in self.model_name:
                params["max_completion_tokens"] = max_tokens
            else:
                params["max_tokens"] = max_tokens

        if response_format:
            params["response_format"] = response_format

        # Merge additional kwargs
        params.update(kwargs)

        try:
            response = self.client.chat.completions.create(**params)
            return response
        except Exception as e:
            logger.error(f"LLM API error: {e}")
            raise

    def get_response_text(self, response: Any) -> str:
        """Extract text from completion response"""
        try:
            return response.choices[0].message.content
        except (AttributeError, IndexError) as e:
            logger.error(f"Failed to extract response text: {e}")
            return ""


# Singleton instance
_llm_client: Optional[LLMClient] = None


def get_llm_client(
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None
) -> LLMClient:
    """
    Get or create LLM client singleton.

    Args:
        api_base: Override API base URL
        api_key: Override API key
        model_name: Override model name

    Returns:
        LLMClient instance
    """
    global _llm_client

    # Create new client if parameters are provided or client doesn't exist
    if api_base or api_key or model_name or _llm_client is None:
        _llm_client = LLMClient(
            api_base=api_base,
            api_key=api_key,
            model_name=model_name
        )

    return _llm_client


# Convenience function for backward compatibility
def create_llm_client() -> Any:
    """
    Create raw OpenAI/Azure client (for legacy code).

    Returns:
        Raw OpenAI or AzureOpenAI client
    """
    client = get_llm_client()
    return client.client
