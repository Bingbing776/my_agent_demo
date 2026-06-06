"""Harness 外层：Planner 队列每次只 pop 一条 → Generator 子任务循环 → 再取下一条。"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from harness.evaluator import HarnessEvaluator
from harness.gates import is_gate_task
from harness.generator import HarnessGenerator
from harness.planner import HarnessPlanner
from harness.types import HarnessSubtaskResult, HarnessTask


class HarnessController:
    def __init__(
        self,
        planner: HarnessPlanner,
        generator: HarnessGenerator,
        evaluator: HarnessEvaluator,
        *,
        verbose: bool = True,
    ):
        self.planner = planner
        self.generator = generator
        self.evaluator = evaluator
        self.verbose = verbose
        self._queue: deque[HarnessTask] = deque()
        self._results: list[HarnessSubtaskResult] = []
        self._start_time: float = 0.0
        self._replan_source_task: HarnessTask | None = None

    def _log(self, msg: str) -> None:
        if self.verbose:
            elapsed = time.time() - self._start_time if self._start_time else 0
            print(f"[{elapsed:7.1f}s] {msg}")

    def _progress_bar(self, done: int, total: int) -> str:
        """生成简单的进度条。"""
        width = 30
        filled = int(width * done / total) if total > 0 else 0
        bar = "█" * filled + "░" * (width - filled)
        pct = (done / total * 100) if total > 0 else 0
        return f"[{bar}] {pct:.0f}% ({done}/{total})"

    def bootstrap_queue(self) -> int:
        self._log("[Planner] 开始规划任务队列...")
        tasks = self.planner.plan()
        self._queue = deque(tasks)
        self.planner._index = len(tasks)

        # 打印队列概览
        unit_count = sum(1 for t in tasks if not is_gate_task(t))
        gate_count = sum(1 for t in tasks if is_gate_task(t))
        self._log(f"[Planner] 任务队列就绪: {len(tasks)} 条 (实现: {unit_count}, 门禁: {gate_count})")
        self._log(f"[Planner] 队列预览:")
        for i, t in enumerate(tasks[:10]):
            kind = "GATE" if is_gate_task(t) else "UNIT"
            self._log(f"  {i+1:3d}. [{kind}] {t.get('id')} — {t.get('title', t.get('symbol', ''))}")
        if len(tasks) > 10:
            self._log(f"  ... 还有 {len(tasks) - 10} 条")
        self._log("")
        return len(self._queue)

    def run(self, *, max_tasks: int | None = None, skip_tasks: int = 0) -> list[dict[str, Any]]:
        self._start_time = time.time()

        if not self._queue:
            self.bootstrap_queue()

        # 跳过前 N 条任务（断点续跑）
        if skip_tasks > 0:
            skipped = 0
            while self._queue and skipped < skip_tasks:
                skipped_task = self._queue.popleft()
                skipped += 1
            self._log(f"[Harness] 跳过前 {skipped} 条任务（断点续跑）\n")

        total_tasks = len(self._queue)
        success_count = 0
        fail_count = 0
        replan_count = 0
        n = 0

        self._log(f"{'='*60}")
        self._log(f"[Harness] 开始执行，共 {total_tasks} 条任务")
        self._log(f"{'='*60}\n")

        while self._queue:
            if max_tasks is not None and n >= max_tasks:
                self._log(f"\n[Harness] 达到 max_tasks={max_tasks}，提前停止")
                break
            task = self._queue.popleft()
            n += 1

            if not str(task.get("id", "")).startswith("replan-"):
                self._replan_source_task = dict(task)

            # 任务开始
            kind = "GATE" if is_gate_task(task) else "UNIT"
            self._log(f"{'─'*60}")
            self._log(
                f"[{kind}] 任务 {n}: {task.get('id')} — {task.get('module', '')}.{task.get('symbol', '')}"
            )
            self._log(f"  目标文件: {task.get('target_file', 'N/A')}")
            self._log(f"  测试文件: {task.get('test_file', '(待 Evaluator 解析)')}")
            self._log(f"  完成标准: {str(task.get('done_criteria', ''))}")
            task_start = time.time()

            # 执行
            result = self.generator.run_subtask(task, self.evaluator)
            self._results.append(result)
            self.generator.invalidate_context_cache()
            if hasattr(self.evaluator, "invalidate_context_cache"):
                self.evaluator.invalidate_context_cache()

            # 任务结束
            status = result.get("status", "failed")
            task_elapsed = time.time() - task_start

            if status == "success":
                success_count += 1
                self._log(f"  OK 通过 ({task_elapsed:.1f}s)")
            elif status == "needs_replan":
                replan_count += 1
                self._log(f"  REPLAN 需要重规划 ({task_elapsed:.1f}s)")
                issues = result.get("observation_for_replan", "")[:150]
                self._log(f"  原因: {issues}")
            else:
                fail_count += 1
                self._log(f"  FAIL 失败 ({task_elapsed:.1f}s)")
                issues = result.get("observation_for_replan", "")[:150]
                self._log(f"  原因: {issues}")

            # 进度
            done = success_count + fail_count + replan_count
            self._log(f"  进度: {self._progress_bar(done, total_tasks + replan_count)}")

            # Replan
            if status in ("needs_replan", "failed"):
                obs = result.get("observation_for_replan", "")
                if is_gate_task(task):
                    gate_id = str(task.get("id", ""))
                    obs = f"[门禁失败] gate_id={gate_id} test_file={task.get('test_file')}\n{obs}"
                failed_for_replan = task
                if str(task.get("id", "")).startswith("replan-"):
                    failed_for_replan = self._replan_source_task or task
                self._log(f"  [Planner] 生成修复任务...")
                fix_tasks = self.planner.replan(obs, failed_task=failed_for_replan)
                for t in reversed(fix_tasks):
                    self._queue.appendleft(t)
                if fix_tasks:
                    self._log(f"  [Planner] 插入 {len(fix_tasks)} 条修复任务到队列前面:")
                    for ft in fix_tasks:
                        fk = "GATE" if is_gate_task(ft) else "FIX"
                        self._log(f"    [{fk}] {ft.get('id')} — {ft.get('symbol', '')}")
                self._log(f"  队列剩余: {len(self._queue)} 条")

            self._log("")

        # 最终汇总
        total_elapsed = time.time() - self._start_time
        self._log(f"{'='*60}")
        self._log(f"[Harness] 执行完毕")
        self._log(f"{'='*60}")
        self._log(f"  总耗时: {total_elapsed:.1f}s")
        self._log(f"  执行任务: {n} 条")
        self._log(f"  OK 成功: {success_count}")
        self._log(f"  FAIL 失败: {fail_count}")
        self._log(f"  REPLAN 重规划: {replan_count}")
        self._log(f"  通过率: {success_count}/{n} ({success_count/n*100:.0f}%)" if n > 0 else "")
        self._log("")

        return [
            {
                "task_id": r.get("task_id"),
                "status": r.get("status"),
                "draft_text": r.get("draft_text"),
            }
            for r in self._results
        ]
