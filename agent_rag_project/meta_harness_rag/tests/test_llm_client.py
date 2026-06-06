"""Tests for Harness LLM base_url normalization."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.llm_client import resolve_factory_base_url

IFLYTEK = "https://example.com/api/llm/chat/completions"
DEEPSEEK = "https://example.com/v1"


def test_custom_provider_keeps_full_endpoint_url():
    assert resolve_factory_base_url("custom", IFLYTEK) == IFLYTEK


def test_openai_provider_strips_chat_completions_suffix():
    assert (
        resolve_factory_base_url("openai", f"{DEEPSEEK}/chat/completions")
        == DEEPSEEK
    )


def test_openai_provider_leaves_base_without_suffix():
    assert resolve_factory_base_url("openai", DEEPSEEK) == DEEPSEEK
