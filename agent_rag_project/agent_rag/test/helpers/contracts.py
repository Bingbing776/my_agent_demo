"""契约断言（阶段 1）。不依赖业务类实现。"""
from __future__ import annotations

import base64
from typing import Any

EVAL_STATUSES = frozenset({"ok", "needs_replan", "hard_fail"})
SUBTASK_STATUSES = frozenset({"success", "failed", "needs_replan"})
NEXT_ACTIONS = frozenset({"call_tool", "stop", "replan"})


def assert_mcp_normalized(raw: dict[str, Any]) -> None:
    assert isinstance(raw.get("content"), list), "content must be list"
    assert isinstance(raw.get("isError"), bool), "isError must be bool"
    for block in raw["content"]:
        assert isinstance(block, dict)
        btype = block.get("type")
        if btype == "text":
            assert "text" in block
        elif btype == "image":
            assert block.get("data"), "image block needs data"


def assert_eval_result(result: dict[str, Any]) -> None:
    for key in ("passed", "score", "require_more_tools", "status", "issues"):
        assert key in result, f"missing EvalResult key: {key}"
    assert result["status"] in EVAL_STATUSES
    if result["status"] == "needs_replan":
        assert result["passed"] is False


def assert_subtask_result(result: dict[str, Any]) -> None:
    for key in ("task_id", "status", "draft_text", "tool_trace", "observation_for_replan"):
        assert key in result, f"missing SubtaskResult key: {key}"
    assert result["status"] in SUBTASK_STATUSES
    for entry in result["tool_trace"]:
        for tk in ("tool_name", "ok", "summary"):
            assert tk in entry, f"tool_trace missing {tk}"


def assert_next_action_result(result: dict[str, Any]) -> None:
    assert result.get("action") in NEXT_ACTIONS
    if result["action"] == "call_tool":
        assert result.get("tool_name")


def assert_global_answer_readiness(result: dict[str, Any]) -> None:
    for key in (
        "sufficient_for_answer",
        "need_replan",
        "issues",
        "observation_for_replan",
    ):
        assert key in result, f"missing GlobalAnswerReadiness key: {key}"
    if result.get("need_replan"):
        assert (result.get("observation_for_replan") or "").strip()


def assert_answer_result(result: dict[str, Any]) -> None:
    assert isinstance(result.get("text"), str)
    images = result.get("images") or []
    assert isinstance(images, list)
    for img in images:
        assert "mime_type" in img and "data" in img
        base64.b64decode(img["data"], validate=True)
