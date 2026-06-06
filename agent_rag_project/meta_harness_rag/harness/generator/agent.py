"""Harness Generator Agent 门面。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.evaluator import HarnessEvaluator
from harness.generator.graph import run_subtask
from harness.generator.runtime import GeneratorRuntime
from harness.llm_client import HarnessLLM
from harness.types import HarnessSubtaskResult, HarnessTask


class HarnessGenerator:
    """
    Generator Agent — LangGraph 子任务内层循环：

    implement → evaluate → (继续 | success | needs_replan | failed)
    """

    def __init__(
        self,
        config: dict | None = None,
        *,
        package_root: Path,
        tech_doc_path: Path,
        harness_cfg: dict | None = None,
        llm: HarnessLLM | None = None,
    ):
        self._runtime = GeneratorRuntime(
            config,
            package_root=package_root,
            tech_doc_path=tech_doc_path,
            harness_cfg=harness_cfg,
            llm=llm,
        )
        self.config = self._runtime.config
        self.package_root = self._runtime.package_root
        self.tech_doc_path = self._runtime.tech_doc_path
        self.harness_cfg = self._runtime.harness_cfg
        self.max_inner_steps = self._runtime.max_inner_steps

    def reset_subtask_state(self) -> None:
        self._runtime.reset_subtask_state()

    def invalidate_context_cache(self) -> None:
        self._runtime.invalidate_context_cache()

    def run_subtask(
        self,
        task: HarnessTask,
        evaluator: HarnessEvaluator,
    ) -> HarnessSubtaskResult:
        return run_subtask(self._runtime, task, evaluator)

    def execute_task(
        self, task: HarnessTask, evaluator: HarnessEvaluator
    ) -> HarnessSubtaskResult:
        return self.run_subtask(task, evaluator)
