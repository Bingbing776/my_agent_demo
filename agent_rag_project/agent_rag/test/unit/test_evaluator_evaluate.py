"""阶段 5.3 — Evaluator.evaluate。见 docs/test_outline.md"""
import json

import pytest
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]


def _mock_llm(content: str):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = content
    mock_llm.chat.return_value = mock_response
    return mock_llm


def test_five_keys(evaluator):
    payload = {
        "passed": True,
        "score": 0.85,
        "require_more_tools": False,
        "status": "ok",
        "issues": "",
    }
    evaluator._llm = _mock_llm(json.dumps(payload))

    result = evaluator.evaluate(
        "TOPMOST 是什么？",
        {"description": "检索 TOPMOST 功能", "intent": "retrieve"},
        "query_knowledge_hub: 命中 3 条",
        "子任务结论：TOPMOST 是 topic modeling 工具包。",
    )

    assert set(result.keys()) == {
        "passed",
        "score",
        "require_more_tools",
        "status",
        "issues",
    }
    assert result["passed"] is True
    assert result["score"] == 0.85
    assert result["require_more_tools"] is False
    assert result["status"] == "ok"


def test_evaluate_empty_trace_retrieve_forces_more_tools(evaluator):
    payload = {
        "passed": True,
        "score": 0.9,
        "require_more_tools": False,
        "status": "ok",
        "issues": "",
    }
    evaluator._llm = _mock_llm(json.dumps(payload))

    result = evaluator.evaluate(
        "q",
        {"description": "retrieve docs", "intent": "retrieve"},
        "",
        "draft",
    )

    assert result["passed"] is False
    assert result["require_more_tools"] is True


def test_evaluate_strict_json_invalid_returns_failed_shape(evaluator):
    evaluator._strict_json = True
    evaluator._llm = _mock_llm("not json at all")

    result = evaluator.evaluate("q", {"description": "d", "intent": "summarize"}, "trace", "draft")

    assert result["passed"] is False
    assert result["require_more_tools"] is True
    assert "issues" in result and result["issues"]
