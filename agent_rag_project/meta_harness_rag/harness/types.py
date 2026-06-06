"""Harness 专用类型（勿与 tech_doc §6 SubtaskResult 混用）。"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class HarnessTask(TypedDict, total=False):
    id: str
    module: str
    section: str
    symbol: str
    title: str
    description: str
    dependencies: list[str]
    target_module: str
    target_class: str
    target_file: str
    test_file: str
    done_criteria: str
    order: int
    # 门禁任务（方案 B，见 harness/gates.py / harness.yaml milestones）
    task_kind: str  # "unit" | "gate"
    pytest_scope: str  # "file" | "directory" | "marker"
    pytest_marker: str
    pytest_extra_args: list[str]
    skip_implementation: bool
    # 门禁允许改产品时：本节 unit 测试 glob（相对 product_root）
    regression_test_globs: list[str]
    optional: bool


class HarnessSubtaskResult(TypedDict, total=False):
    task_id: str
    status: Literal["success", "failed", "needs_replan"]
    draft_text: str
    tool_trace: list[dict[str, Any]]
    observation_for_replan: str
    artifacts: dict[str, Any]


class HarnessEvalResult(TypedDict, total=False):
    passed: bool
    score: float
    require_more_tools: bool
    status: Literal["ok", "needs_replan", "hard_fail"]
    issues: str
