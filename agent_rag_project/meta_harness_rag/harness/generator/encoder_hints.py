"""向后兼容：DenseEncoder hint API 已迁至 harness.integration_hints。"""
from harness.integration_hints import (
    ENCODER_RELATED_SYMBOLS,
    encoder_implementation_hint,
    needs_encoder_hint,
    related_symbols_from_issues,
)

__all__ = [
    "ENCODER_RELATED_SYMBOLS",
    "encoder_implementation_hint",
    "needs_encoder_hint",
    "related_symbols_from_issues",
]
