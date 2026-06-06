"""Factory for creating Evaluator provider instances.

This module implements the Factory Pattern to instantiate the appropriate
Evaluator provider based on configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.evaluator.base_evaluator import BaseEvaluator, NoneEvaluator
from src.libs.evaluator.custom_evaluator import CustomEvaluator

if TYPE_CHECKING:
    from src.core.settings import Settings


class EvaluatorFactory:
    """Factory for creating Evaluator provider instances.

    Design Principles Applied:
    - Factory Pattern: Centralizes object creation logic.
    - Config-Driven: Provider selection based on settings.yaml.
    - Fallback: Disabled evaluation returns NoneEvaluator.
    - Fail-Fast: Raises clear errors for unknown providers.
    """

    _PROVIDERS: dict[str, type[BaseEvaluator]] = {
        "custom": CustomEvaluator,
    }

    @classmethod
    def register_provider(cls, name: str, provider_class: type[BaseEvaluator]) -> None:
        """Register a new Evaluator provider implementation."""
        if not issubclass(provider_class, BaseEvaluator):
            raise ValueError(
                f"Provider class {provider_class.__name__} must inherit from BaseEvaluator"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: Settings, **override_kwargs: Any) -> BaseEvaluator:
        """Create an Evaluator instance based on configuration."""
        try:
            if hasattr(settings, "evaluation"):
                evaluation_settings = settings.evaluation
            elif hasattr(settings, "provider") and hasattr(settings, "enabled"):
                evaluation_settings = settings
            else:
                raise AttributeError("settings has no 'evaluation' attribute")
            if evaluation_settings is None:
                raise AttributeError("settings.evaluation is None")
            provider_name = evaluation_settings.provider.lower()
            enabled = bool(evaluation_settings.enabled)
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.evaluation.provider. "
                "Please ensure 'evaluation.provider' is specified in settings.yaml"
            ) from e

        if not enabled or provider_name in {"none", "disabled"}:
            return NoneEvaluator(settings=settings, **override_kwargs)

        provider_class = cls._PROVIDERS.get(provider_name)
        if provider_class is None:
            available = ", ".join(sorted(cls._PROVIDERS.keys())) if cls._PROVIDERS else "none"
            raise ValueError(
                f"Unsupported Evaluator provider: '{provider_name}'. "
                f"Available providers: {available}."
            )

        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate Evaluator provider '{provider_name}': {e}"
            ) from e

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names."""
        return sorted(cls._PROVIDERS.keys())