"""Harness Planner LangGraph 编排。"""
from __future__ import annotations

from harness.planner.runtime import PlannerRuntime
from harness.planner.state import PlannerPlanState, PlannerReplanState
from harness.types import HarnessTask

try:
    from langgraph.graph import END, StateGraph
except ImportError as e:
    raise ImportError(
        "LangGraph 未安装。请在 meta_harness_rag 目录执行: pip install -r requirements.txt"
    ) from e


def _route_after_llm_replan(state: PlannerReplanState) -> str:
    if state.get("fix_tasks"):
        return "append"
    return "fallback"


def build_plan_graph(runtime: PlannerRuntime):
    """plan：load_doc → parse_tasks → enrich_tasks → finalize_plan → END"""
    g = StateGraph(PlannerPlanState)
    g.add_node("load_doc", runtime.node_load_doc)
    g.add_node("parse_tasks", runtime.node_parse_tasks)
    g.add_node("enrich_tasks", runtime.node_enrich_tasks)
    g.add_node("finalize_plan", runtime.node_finalize_plan)
    g.set_entry_point("load_doc")
    g.add_edge("load_doc", "parse_tasks")
    g.add_edge("parse_tasks", "enrich_tasks")
    g.add_edge("enrich_tasks", "finalize_plan")
    g.add_edge("finalize_plan", END)
    return g.compile()


def build_replan_graph(runtime: PlannerRuntime):
    """replan：llm_replan → (fallback?) → append_replan → END"""
    g = StateGraph(PlannerReplanState)
    g.add_node("llm_replan", runtime.node_llm_replan)
    g.add_node("fallback_replan", runtime.node_fallback_replan)
    g.add_node("append_replan", runtime.node_append_replan)
    g.set_entry_point("llm_replan")
    g.add_conditional_edges(
        "llm_replan",
        _route_after_llm_replan,
        {"append": "append_replan", "fallback": "fallback_replan"},
    )
    g.add_edge("fallback_replan", "append_replan")
    g.add_edge("append_replan", END)
    return g.compile()


def get_plan_graph(runtime: PlannerRuntime):
    if runtime._plan_graph_app is None:
        runtime._plan_graph_app = build_plan_graph(runtime)
    return runtime._plan_graph_app


def get_replan_graph(runtime: PlannerRuntime):
    if runtime._replan_graph_app is None:
        runtime._replan_graph_app = build_replan_graph(runtime)
    return runtime._replan_graph_app


def run_plan(runtime: PlannerRuntime) -> list[HarnessTask]:
    if runtime._planned:
        return list(runtime._queue)
    final = get_plan_graph(runtime).invoke({})
    return runtime.apply_plan_result(final)


def run_replan(
    runtime: PlannerRuntime,
    observation: str,
    *,
    failed_task: HarnessTask | None = None,
) -> list[HarnessTask]:
    initial: PlannerReplanState = {
        "observation": observation,
        "queue_index": runtime._index,
    }
    if failed_task:
        initial["failed_task"] = dict(failed_task)
    final = get_replan_graph(runtime).invoke(initial)
    return list(final.get("fix_tasks") or [])
