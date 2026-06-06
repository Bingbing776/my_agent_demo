"""LangGraph Evaluator 状态。"""
from __future__ import annotations

from typing import Any, TypedDict

from harness.types import HarnessEvalResult, HarnessTask


class EvaluatorState(TypedDict, total=False):
    task: HarnessTask
    tool_trace_summary: str
    draft_text: str

    hard_fail: bool
    eval_result: HarnessEvalResult

    test_note: str
    test_action: str
    test_reason: str
    pytest_out: str
    rule_result: HarnessEvalResult

    progress_icon: str
    progress_note: str
    tests_just_updated: bool
    progress_sync_note: str

    meta: dict[str, Any]
