"""LangGraph Planner 状态。"""
from __future__ import annotations

from typing import Any, TypedDict

from harness.types import HarnessTask


class PlannerPlanState(TypedDict, total=False):
    doc_text: str
    tasks: list[HarnessTask]
    planned: bool


class PlannerReplanState(TypedDict, total=False):
    observation: str
    failed_task: HarnessTask
    fix_tasks: list[HarnessTask]
    queue_index: int
