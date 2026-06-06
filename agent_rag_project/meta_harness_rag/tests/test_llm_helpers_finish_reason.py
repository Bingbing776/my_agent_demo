"""Tests for finish_reason logging helpers in harness.llm_helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.llm_helpers import _extract_finish_reason, _log_chat_usage


@dataclass
class _FakeResp:
    content: str
    model: str
    usage: dict[str, int] | None = None
    raw_response: dict[str, Any] | None = None


def test_extract_finish_reason_from_raw_response():
    resp = _FakeResp(
        content="ok",
        model="claude-opus-4-6",
        raw_response={"choices": [{"finish_reason": "stop"}]},
    )
    assert _extract_finish_reason(resp) == "stop"


def test_extract_finish_reason_missing():
    assert _extract_finish_reason(_FakeResp(content="", model="m")) == ""


def test_log_chat_usage_length_emits_warning(caplog):
    import logging

    caplog.set_level(logging.WARNING)
    resp = _FakeResp(
        content="partial",
        model="claude-opus-4-6",
        usage={"completion_tokens": 32000},
        raw_response={"choices": [{"finish_reason": "length"}]},
    )
    _log_chat_usage(resp, harness_cfg={"llm": {"max_tokens": 32768}}, agent_key="generator")
    assert any("finish_reason=length" in r.message for r in caplog.records)
    assert any("agent=generator" in r.message for r in caplog.records)
