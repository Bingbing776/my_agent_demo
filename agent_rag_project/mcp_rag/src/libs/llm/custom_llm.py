"""Custom LLM implementation for third-party relay/proxy APIs.

This module provides a custom LLM provider that sends requests directly
to the configured base_url WITHOUT appending /chat/completions.
Use this when your API relay endpoint is a full URL.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from src.libs.llm.base_llm import BaseLLM, ChatResponse, Message


class CustomLLMError(RuntimeError):
    """Raised when Custom LLM API call fails."""


class CustomLLM(BaseLLM):
    """Custom LLM provider for relay/proxy APIs with non-standard URL patterns.

    Unlike OpenAILLM which appends /chat/completions to base_url,
    this provider uses base_url as the complete endpoint URL.

    Example config in settings.yaml:
        llm:
          provider: "custom"
          model: "claude-opus-4.6"
          base_url: "https://your-custom-llm-endpoint.com/api/chat"
          api_key: "sk-xxx"
    """

    def __init__(
        self,
        settings: Any,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.model = settings.llm.model
        self.default_temperature = settings.llm.temperature
        self.default_max_tokens = settings.llm.max_tokens

        # API key: explicit > settings > env var
        self.api_key = (
            api_key
            or getattr(settings.llm, 'api_key', None)
            or os.environ.get("OPENAI_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "API key not provided. Set in settings.yaml (llm.api_key), "
                "OPENAI_API_KEY environment variable, or pass api_key parameter."
            )

        # base_url is used as-is, no path appending
        self.base_url = (
            base_url
            or getattr(settings.llm, 'base_url', None)
        )
        if not self.base_url:
            raise ValueError(
                "base_url is required for custom provider. "
                "Set llm.base_url in settings.yaml."
            )

    def chat(
        self,
        messages: List[Message],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate a chat completion using the custom API endpoint."""
        self.validate_messages(messages)

        temperature = kwargs.get("temperature", self.default_temperature)
        max_tokens = kwargs.get("max_tokens", self.default_max_tokens)
        model = kwargs.get("model", self.model)

        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        try:
            response_data = self._call_api(
                messages=api_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response_data["choices"][0]["message"]["content"]
            usage = response_data.get("usage")

            return ChatResponse(
                content=content,
                model=response_data.get("model", model),
                usage=usage,
                raw_response=response_data,
            )
        except KeyError as e:
            raise CustomLLMError(
                f"[Custom] Unexpected response format: missing key {e}"
            ) from e
        except Exception as e:
            if isinstance(e, CustomLLMError):
                raise
            raise CustomLLMError(
                f"[Custom] API call failed: {type(e).__name__}: {e}"
            ) from e

    def _call_api(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """Make the API call directly to base_url (no path appending)."""
        import httpx

        # Use base_url directly as the full endpoint
        url = self.base_url

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                response = client.post(url, json=payload, headers=headers)

                if response.status_code != 200:
                    error_detail = self._parse_error_response(response)
                    raise CustomLLMError(
                        f"[Custom] API error (HTTP {response.status_code}): {error_detail}"
                    )

                # Debug: print actual response for troubleshooting
                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type:
                    raise CustomLLMError(
                        f"[Custom] Expected JSON but got content-type: {content_type}. "
                        f"Final URL: {response.url}. "
                        f"Response preview: {response.text[:200]}"
                    )

                return response.json()
        except httpx.TimeoutException as e:
            raise CustomLLMError(
                "[Custom] Request timed out after 120 seconds"
            ) from e
        except httpx.RequestError as e:
            raise CustomLLMError(
                f"[Custom] Connection failed: {type(e).__name__}: {e}"
            ) from e

    def _parse_error_response(self, response: Any) -> str:
        """Parse error details from API response."""
        try:
            error_data = response.json()
            if "error" in error_data:
                error = error_data["error"]
                if isinstance(error, dict):
                    return error.get("message", str(error))
                return str(error)
            return response.text
        except Exception:
            return response.text or "Unknown error"
