"""Harness Evaluator LangGraph 编排。"""
from __future__ import annotations

from typing import Literal

from harness.evaluator.runtime import EvaluatorRuntime
from harness.evaluator.state import EvaluatorState
from harness.types import HarnessEvalResult, HarnessTask

try:
    from langgraph.graph import END, StateGraph
except ImportError as e:
    raise ImportError(
        "LangGraph 未安装。请在 meta_harness_rag 目录执行: pip install -r requirements.txt"
    ) from e


def _route_after_quick_rule(state: EvaluatorState) -> Literal["update_progress", "apply_index"]:
    if state.get("hard_fail"):
        return "update_progress"
    return "apply_index"


def build_evaluator_graph(runtime: EvaluatorRuntime):
    """
    Evaluator 主图（LangGraph）：

    quick_rule → apply_index → assess_ensure_tests → rule_evaluate
        → llm_evaluate | merge_rule → update_test_progress → END
    quick_rule(hard_fail) → update_test_progress → END
    """
    graph = StateGraph(EvaluatorState)

    graph.add_node("quick_rule", runtime.node_quick_rule)
    graph.add_node("apply_index", runtime.node_apply_index)
    graph.add_node("assess_ensure_tests", runtime.node_assess_and_ensure_tests)
    graph.add_node("rule_evaluate", runtime.node_rule_evaluate)
    graph.add_node("llm_evaluate", runtime.node_llm_evaluate)
    graph.add_node("merge_rule", runtime.node_merge_rule_only)
    graph.add_node("update_test_progress", runtime.node_update_test_progress)

    graph.set_entry_point("quick_rule")

    graph.add_conditional_edges(
        "quick_rule",
        _route_after_quick_rule,
        {"update_progress": "update_test_progress", "apply_index": "apply_index"},
    )
    graph.add_edge("apply_index", "assess_ensure_tests")
    graph.add_edge("assess_ensure_tests", "rule_evaluate")

    if runtime._llm:
        graph.add_edge("rule_evaluate", "llm_evaluate")
        graph.add_edge("llm_evaluate", "update_test_progress")
    else:
        graph.add_edge("rule_evaluate", "merge_rule")
        graph.add_edge("merge_rule", "update_test_progress")
    graph.add_edge("update_test_progress", END)

    return graph.compile()


def get_compiled_graph(runtime: EvaluatorRuntime):
    if runtime._graph_app is None:
        runtime._graph_app = build_evaluator_graph(runtime)
    return runtime._graph_app


def run_evaluate(
    runtime: EvaluatorRuntime,
    task: HarnessTask,
    tool_trace_summary: str,
    draft_text: str,
) -> HarnessEvalResult:
    """执行编译后的 LangGraph，返回评估结果。"""
    app = get_compiled_graph(runtime)
    task = dict(task)
    runtime.apply_index_to_task(task)
    initial: EvaluatorState = {
        "task": task,
        "tool_trace_summary": tool_trace_summary,
        "draft_text": draft_text,
        "hard_fail": False,
        "test_note": "",
        "pytest_out": "",
    }
    final = app.invoke(initial)
    if final.get("hard_fail") and final.get("eval_result"):
        return final["eval_result"]
    if final.get("eval_result"):
        return final["eval_result"]
    if final.get("rule_result"):
        return final["rule_result"]
    return HarnessEvalResult(
        passed=False,
        score=0.0,
        require_more_tools=True,
        status="ok",
        issues="Evaluator 图未产生 eval_result",
    )
