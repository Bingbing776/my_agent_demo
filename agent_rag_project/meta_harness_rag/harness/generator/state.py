"""LangGraph Generator 子任务内层循环状态。"""
from __future__ import annotations

from typing import Any, TypedDict

from harness.types import HarnessEvalResult, HarnessSubtaskResult, HarnessTask


class GeneratorSubtaskState(TypedDict, total=False):
    task: HarnessTask
    draft_text: str
    step_count: int
    last_eval: HarnessEvalResult | None
    inner_trace: list[dict[str, Any]]
    subtask_result: HarnessSubtaskResult | None
    terminal: bool
