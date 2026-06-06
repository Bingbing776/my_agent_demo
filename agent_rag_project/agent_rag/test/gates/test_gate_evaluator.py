"""§5 — Evaluator 功能门禁验收。"""
import json

import pytest
from unittest.mock import MagicMock

pytestmark = [pytest.mark.gate]


def _mock_llm(content: str):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = content
    mock_llm.chat.return_value = mock_response
    return mock_llm


def test_evaluator_init(evaluator):
    assert evaluator is not None
    assert isinstance(evaluator._config, dict)
    assert evaluator._llm is not None
    assert hasattr(evaluator._llm, "chat")
    assert not hasattr(evaluator, "_executor")
    assert not hasattr(evaluator, "_mcp_client")


def test_evaluate_returns_eval_result(evaluator):
    evaluator._llm = _mock_llm(
        json.dumps(
            {
                "passed": True,
                "score": 0.8,
                "require_more_tools": False,
                "status": "ok",
                "issues": "",
            }
        )
    )
    result = evaluator.evaluate(
        "What is TOPMOST?",
        {"description": "Find TOPMOST features", "intent": "retrieve"},
        "query_knowledge_hub: 3 hits",
        "TOPMOST is a topic modeling toolkit.",
    )
    assert set(result.keys()) == {
        "passed",
        "score",
        "require_more_tools",
        "status",
        "issues",
    }


def test_quick_rule_check_hard_fail(evaluator):
    trace = "[error] a\n[error] b\n[error] c"
    result = evaluator.quick_rule_check({"intent": "retrieve"}, trace)
    assert result is not None
    assert result["status"] == "hard_fail"
    assert result["passed"] is False
