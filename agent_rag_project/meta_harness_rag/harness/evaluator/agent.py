"""Harness Evaluator Agent：LangGraph 编排 + function calling 读文件。"""
from __future__ import annotations

from pathlib import Path

from harness.evaluator.graph import run_evaluate
from harness.evaluator.runtime import EvaluatorRuntime
from harness.llm_client import HarnessLLM
from harness.types import HarnessEvalResult, HarnessTask


class HarnessEvaluator:
    """
    Evaluator 对外门面。

    内部由 LangGraph 状态图驱动（见 ``harness/evaluator/graph.py``）：
    quick_rule → apply_index → assess/ensure_tests → rule_evaluate → llm_evaluate → update_test_progress。

    测试完备性判断与写测试支持 function calling（``read_file`` 等），
    LLM 自行从 ``agent_rag/test/`` 读取所需文件。
    """

    def __init__(
        self,
        config: dict | None = None,
        *,
        package_root: Path,
        harness_cfg: dict | None = None,
        llm: HarnessLLM | None = None,
        tech_doc_path: Path | None = None,
    ):
        self._runtime = EvaluatorRuntime(
            config,
            package_root=package_root,
            harness_cfg=harness_cfg,
            llm=llm,
            tech_doc_path=tech_doc_path,
        )
        self.config = self._runtime.config
        self.harness_cfg = self._runtime.harness_cfg
        self.package_root = self._runtime.package_root
        self.product_root = self._runtime.product_root
        self.tech_doc_path = self._runtime.tech_doc_path
        self._llm = self._runtime._llm

    def evaluate(
        self,
        task: HarnessTask,
        tool_trace_summary: str,
        draft_text: str,
    ) -> HarnessEvalResult:
        return run_evaluate(self._runtime, task, tool_trace_summary, draft_text)

    def ensure_test_file(self, task: HarnessTask, draft_text: str) -> tuple[bool, str]:
        """单独触发测试检查/写入（与图内 assess 节点逻辑一致）。"""
        self._runtime.apply_index_to_task(task)
        action, reason = self._runtime.decide_test_action(task, draft_text)
        if action == "skip":
            return False, f"LLM 判定测试已完备，跳过: {reason}"
        return self._runtime.write_test_file(task, draft_text, action=action, reason=reason)

    def quick_rule_check(
        self,
        task: HarnessTask,
        tool_trace_summary: str,
    ) -> HarnessEvalResult | None:
        out = self._runtime.node_quick_rule(
            {"task": task, "tool_trace_summary": tool_trace_summary}
        )
        if out.get("hard_fail"):
            self.record_progress(
                task,
                tool_trace_summary,
                out["eval_result"],
                progress_icon=out.get("progress_icon"),
                progress_note=out.get("progress_note"),
            )
            return out["eval_result"]
        return None

    def record_progress(
        self,
        task: HarnessTask,
        tool_trace_summary: str,
        eval_result: HarnessEvalResult,
        *,
        progress_icon: str | None = None,
        progress_note: str | None = None,
        tests_just_updated: bool = False,
        test_note: str = "",
    ) -> str:
        """按评估结果更新 TEST_PROGRESS（不经完整 LangGraph 时也可调用）。"""
        out = self._runtime.node_update_test_progress(
            {
                "task": dict(task),
                "tool_trace_summary": tool_trace_summary,
                "eval_result": eval_result,
                "progress_icon": progress_icon,
                "progress_note": progress_note,
                "tests_just_updated": tests_just_updated,
                "test_note": test_note,
            }
        )
        return str(out.get("progress_sync_note", ""))

    def invalidate_context_cache(self) -> None:
        self._runtime.invalidate_context_cache()

    def to_planner_observation(
        self, eval_result: HarnessEvalResult, max_chars: int | None = None,
        *, task=None, step_count: int | None = None,
    ) -> str:
        return self._runtime.to_planner_observation(
            eval_result, max_chars, task=task, step_count=step_count
        )
