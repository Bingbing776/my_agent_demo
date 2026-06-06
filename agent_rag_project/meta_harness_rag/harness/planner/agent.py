"""Harness Planner Agent 门面。"""
from __future__ import annotations

from pathlib import Path

from harness.llm_client import HarnessLLM
from harness.planner.graph import run_plan, run_replan
from harness.planner.runtime import PlannerRuntime
from harness.types import HarnessTask


class HarnessPlanner:
    """
    Planner Agent（Harness）— LangGraph 编排：

    - ``plan`` 图：load_doc → parse_tasks → enrich_tasks → finalize_plan
    - ``replan`` 图：llm_replan → fallback_replan → append_replan
    """

    def __init__(
        self,
        tech_doc_path: str | Path,
        *,
        config: dict | None = None,
        package_root: str | Path | None = None,
        harness_cfg: dict | None = None,
        llm: HarnessLLM | None = None,
    ):
        self.tech_doc_path = Path(tech_doc_path)
        self.package_root = Path(package_root or self.tech_doc_path.parents[1])
        self._runtime = PlannerRuntime(
            self.tech_doc_path,
            config=config,
            package_root=self.package_root,
            harness_cfg=harness_cfg or config,
            llm=llm,
        )
        self.config = self._runtime.config
        self.harness_cfg = self._runtime.harness_cfg

    @property
    def _queue(self) -> list[HarnessTask]:
        return self._runtime._queue

    @_queue.setter
    def _queue(self, value: list[HarnessTask]) -> None:
        self._runtime._queue = value

    @property
    def _index(self) -> int:
        return self._runtime._index

    @_index.setter
    def _index(self, value: int) -> None:
        self._runtime._index = value

    def plan(self) -> list[HarnessTask]:
        return run_plan(self._runtime)

    def get_next_task(self) -> HarnessTask | None:
        if not self._runtime._planned:
            self.plan()
        if self._runtime._index >= len(self._runtime._queue):
            return None
        task = self._runtime._queue[self._runtime._index]
        self._runtime._index += 1
        return task

    def remaining(self) -> int:
        if not self._runtime._planned:
            self.plan()
        return max(0, len(self._runtime._queue) - self._runtime._index)

    def replan(
        self,
        observation: str,
        *,
        failed_task: HarnessTask | None = None,
    ) -> list[HarnessTask]:
        return run_replan(self._runtime, observation, failed_task=failed_task)
