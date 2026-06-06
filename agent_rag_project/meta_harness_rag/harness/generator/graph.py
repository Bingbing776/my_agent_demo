"""Harness Generator LangGraph 编排（子任务内 Gen↔Eval 循环）。"""
from __future__ import annotations

from typing import Literal

from harness.gates import gate_allows_product_fix, is_gate_task
from harness.generator.runtime import GeneratorRuntime
from harness.generator.state import GeneratorSubtaskState
from harness.types import HarnessEvalResult, HarnessSubtaskResult, HarnessTask

try:
    from langgraph.graph import END, StateGraph
except ImportError as e:
    raise ImportError(
        "LangGraph 未安装。请在 meta_harness_rag 目录执行: pip install -r requirements.txt"
    ) from e


def _route_entry(state: GeneratorSubtaskState) -> Literal["implement", "evaluate"]:
    task = state.get("task") or {}
    if is_gate_task(task) and not gate_allows_product_fix(task):
        return "evaluate"
    return "implement"


def _route_after_evaluate(state: GeneratorSubtaskState) -> Literal["implement", "end"]:
    if state.get("terminal"):
        return "end"
    task = state.get("task") or {}
    if is_gate_task(task) and not gate_allows_product_fix(task):
        return "end"
    return "implement"


def build_subtask_graph(runtime: GeneratorRuntime):
    """
    子任务内层图：implement → evaluate → (继续 implement | END)
    门禁任务：evaluate 单轮（入口直连 evaluate）。
    """
    g = StateGraph(GeneratorSubtaskState)
    g.add_node("implement", runtime.node_implement)
    g.add_node("evaluate", runtime.node_evaluate)
    g.set_conditional_entry_point(
        _route_entry,
        {"implement": "implement", "evaluate": "evaluate"},
    )
    g.add_edge("implement", "evaluate")
    g.add_conditional_edges(
        "evaluate",
        _route_after_evaluate,
        {"implement": "implement", "end": END},
    )
    return g.compile()


def get_subtask_graph(runtime: GeneratorRuntime):
    if runtime._subtask_graph_app is None:
        runtime._subtask_graph_app = build_subtask_graph(runtime)
    return runtime._subtask_graph_app


def run_subtask(
    runtime: GeneratorRuntime,
    task: HarnessTask,
    evaluator,
) -> HarnessSubtaskResult:
    runtime.set_evaluator(evaluator)
    runtime.reset_subtask_state()
    initial: GeneratorSubtaskState = {
        "task": dict(task),
        "draft_text": "",
        "step_count": 0,
        "last_eval": None,
        "inner_trace": [],
        "subtask_result": None,
        "terminal": False,
    }
    final = get_subtask_graph(runtime).invoke(initial)
    if final.get("subtask_result"):
        return final["subtask_result"]
    task_id = str(task.get("id", "unknown"))
    return HarnessSubtaskResult(
        task_id=task_id,
        status="failed",
        draft_text=final.get("draft_text", ""),
        tool_trace=list(final.get("inner_trace") or []),
        observation_for_replan="Generator 图未产生 subtask_result",
        artifacts={},
    )
