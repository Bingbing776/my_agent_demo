"""Planner 业务逻辑与 LangGraph 节点。"""
from __future__ import annotations

import re
from pathlib import Path

from harness.llm_client import HarnessLLM, create_harness_llm
from harness.llm_helpers import chat, parse_json_array, parse_json_object
from harness.gates import inject_gate_tasks, is_gate_task
from harness.planner.parsing import parse_all_tasks
from harness.integration_hints import collect_integration_hints, integration_hints_enabled
from harness.types import HarnessTask

_OBS_FIELD_PATTERNS: dict[str, str] = {
    "id": r"(?:子任务:\s*)?id=([^\s]+)",
    "symbol": r"symbol=([^\s]+)",
    "target_file": r"target_file=([^\s]+)",
    "test_file": r"test_file=([^\s]+)",
    "target_class": r"target_class=([^\s]+)",
}


def parse_observation_task_hints(observation: str) -> dict[str, str]:
    """从 to_planner_observation / Generator 观测文本中解析任务字段。"""
    hints: dict[str, str] = {}
    for key, pattern in _OBS_FIELD_PATTERNS.items():
        m = re.search(pattern, observation)
        if not m:
            continue
        val = m.group(1).strip()
        if val and val not in ("None", "null", "N/A"):
            hints[key] = val
    return hints


def backfill_fix_task(
    fix: HarnessTask,
    *,
    observation: str = "",
    failed_task: HarnessTask | None = None,
) -> HarnessTask:
    """LLM replan 漏填字段时，从 failed_task 与 observation 回填 target_file 等。"""
    out: HarnessTask = dict(fix)
    hints = parse_observation_task_hints(observation)
    source: dict[str, str] = {}
    if failed_task:
        for key in (
            "id",
            "symbol",
            "target_file",
            "test_file",
            "target_class",
            "target_module",
            "module",
            "section",
            "title",
            "done_criteria",
        ):
            val = failed_task.get(key)
            if val is not None and str(val).strip() and str(val) not in ("None", "N/A"):
                source[key] = str(val)

    def _pick(field: str) -> str:
        cur = str(out.get(field, "")).strip()
        if cur and cur not in ("None", "N/A"):
            return cur
        if hints.get(field):
            return hints[field]
        return source.get(field, "")

    for field in (
        "target_file",
        "test_file",
        "symbol",
        "target_class",
        "target_module",
        "module",
        "section",
    ):
        picked = _pick(field)
        if picked:
            out[field] = picked

    if str(out.get("symbol", "")).strip() in ("", "fix"):
        if hints.get("symbol"):
            out["symbol"] = hints["symbol"]
        elif source.get("symbol"):
            out["symbol"] = source["symbol"]
    if str(out.get("module", "")).strip() in ("", "(replan)"):
        if source.get("module"):
            out["module"] = source["module"]
    if not str(out.get("title", "")).strip() and source.get("title"):
        out["title"] = f"修复 {source.get('symbol', source.get('id', ''))}"
    if str(out.get("done_criteria", "")).strip() in ("", "evaluator 通过") and source.get(
        "done_criteria"
    ):
        out["done_criteria"] = source["done_criteria"]
    return out


class PlannerRuntime:
    def __init__(
        self,
        tech_doc_path: Path,
        *,
        config: dict | None = None,
        package_root: Path,
        harness_cfg: dict | None = None,
        llm: HarnessLLM | None = None,
    ):
        self.tech_doc_path = tech_doc_path
        self.config = config or {}
        self.harness_cfg = harness_cfg or self.config
        self.package_root = package_root
        self._planner_cfg = self.harness_cfg.get("planner") or {}

        self._llm: HarnessLLM | None = llm
        if self._llm is None and self._use_llm():
            self._llm = create_harness_llm(self.harness_cfg, package_root)

        self._queue: list[HarnessTask] = []
        self._index = 0
        self._planned = False
        self._doc_cache: str | None = None
        self._plan_graph_app = None
        self._replan_graph_app = None

    def _use_llm(self) -> bool:
        if self.harness_cfg.get("llm_enabled") is False:
            return False
        return self._planner_cfg.get("use_llm", True)

    def read_doc(self) -> str:
        if self._doc_cache is None:
            self._doc_cache = self.tech_doc_path.read_text(encoding="utf-8")
        return self._doc_cache

    def node_load_doc(self, state: dict) -> dict:
        return {"doc_text": self.read_doc(), "planned": False}

    def node_parse_tasks(self, state: dict) -> dict:
        tasks = parse_all_tasks(state.get("doc_text", ""), self.config)
        tasks = inject_gate_tasks(tasks, self.harness_cfg)
        return {"tasks": tasks}

    def _enrich_batch_size(self) -> int:
        """每批送入 LLM 的 unit 任务数；兼容旧键 enrich_max_tasks。"""
        raw = self._planner_cfg.get("enrich_batch_size")
        if raw is None:
            raw = self._planner_cfg.get("enrich_max_tasks", 30)
        return max(1, int(raw))

    def _enrich_task_limit(self) -> int | None:
        """最多 enrich 的 unit 任务总数；None 表示不限制（全部 enrich）。"""
        raw = self._planner_cfg.get("enrich_task_limit")
        if raw is None:
            return None
        limit = int(raw)
        return limit if limit > 0 else None

    @staticmethod
    def _enrich_system_prompt() -> str:
        return (
            "你是 Harness Planner Agent。根据 tech_doc 为每个实现子任务写 description 与 done_criteria。"
            "只输出 JSON 数组，每项对象含 id、description、done_criteria（均为 str）。"
            "不要增删任务 id。"
        )

    def _merge_enriched_tasks(
        self, tasks: list[HarnessTask], by_id: dict[str, dict]
    ) -> list[HarnessTask]:
        out: list[HarnessTask] = []
        for t in tasks:
            item = by_id.get(str(t.get("id")))
            if not item:
                out.append(t)
                continue
            nt: HarnessTask = dict(t)
            if item.get("description"):
                nt["description"] = str(item["description"])
            if item.get("done_criteria"):
                nt["done_criteria"] = str(item["done_criteria"])
            out.append(nt)
        return out

    def node_enrich_tasks(self, state: dict) -> dict:
        tasks = list(state.get("tasks") or [])
        if not self._llm or not self._planner_cfg.get("enrich_descriptions", True):
            return {"tasks": tasks}

        unit_tasks = [t for t in tasks if not is_gate_task(t)]
        limit = self._enrich_task_limit()
        if limit is not None:
            unit_tasks = unit_tasks[:limit]

        if not unit_tasks:
            return {"tasks": tasks}

        batch_size = self._enrich_batch_size()
        text = state.get("doc_text", "")
        system = self._enrich_system_prompt()
        doc_excerpt = text[:200000]
        by_id: dict[str, dict] = {}

        for start in range(0, len(unit_tasks), batch_size):
            batch = unit_tasks[start : start + batch_size]
            lines = [
                f"- id={t.get('id')} symbol={t.get('symbol')} file={t.get('target_file')} deps={t.get('dependencies')}"
                for t in batch
            ]
            batch_no = start // batch_size + 1
            batch_total = (len(unit_tasks) + batch_size - 1) // batch_size
            user = (
                f"任务列表（第 {batch_no}/{batch_total} 批，本批 {len(batch)} 条）：\n"
                + "\n".join(lines)
                + "\n\ntech_doc 节选：\n"
                + doc_excerpt
            )
            try:
                raw = chat(
                    self._llm,
                    system=system,
                    user=user,
                    harness_cfg=self.harness_cfg,
                    agent_key="planner",
                )
                arr = parse_json_array(raw)
                for x in arr:
                    if isinstance(x, dict) and x.get("id"):
                        by_id[str(x.get("id"))] = x
            except Exception:
                continue

        if not by_id:
            return {"tasks": tasks}
        return {"tasks": self._merge_enriched_tasks(tasks, by_id)}

    def node_finalize_plan(self, state: dict) -> dict:
        tasks = sorted(state.get("tasks") or [], key=lambda t: t.get("order", 0))
        self._queue = tasks
        self._index = 0
        self._planned = True
        return {"tasks": tasks, "planned": True}

    def _normalize_fix_tasks(self, fixes: list[HarnessTask], state: dict) -> list[HarnessTask]:
        observation = str(state.get("observation", ""))
        failed_task = state.get("failed_task")
        return [
            backfill_fix_task(t, observation=observation, failed_task=failed_task)
            for t in fixes
        ]

    def _replan_user_prompt(self, observation: str, failed_task: HarnessTask | None) -> str:
        parts = [f"失败观测：\n{observation[:50000]}"]
        if failed_task:
            parts.append(
                "\n\n失败任务（修复子任务必须继承以下 target_file / symbol，不可留空）：\n"
                f"- id={failed_task.get('id')}\n"
                f"- symbol={failed_task.get('symbol')}\n"
                f"- target_file={failed_task.get('target_file')}\n"
                f"- test_file={failed_task.get('test_file')}\n"
                f"- target_class={failed_task.get('target_class')}\n"
                f"- done_criteria={failed_task.get('done_criteria')}"
            )
            hints = self._replan_integration_hints(failed_task, observation)
            if hints:
                parts.append("\n\n" + hints)
        parts.append("\n\n请给出修正子任务。")
        return "".join(parts)

    def _replan_integration_hints(self, failed_task: HarnessTask, observation: str) -> str:
        if not integration_hints_enabled(self.harness_cfg):
            return ""
        symbol = str(failed_task.get("symbol") or "")
        target = str(failed_task.get("target_file") or "")
        return collect_integration_hints(
            symbol=symbol,
            issues=observation,
            target_file=target,
            primary_symbol=symbol,
        )

    def node_llm_replan(self, state: dict) -> dict:
        observation = state.get("observation", "")
        failed_task = state.get("failed_task")
        if not self._llm or not self._planner_cfg.get("replan_use_llm", True):
            return {"fix_tasks": []}
        system = (
            "你是 Harness Planner Agent。根据实现失败观测，生成修正子任务。\n\n"
            "观测（observation）可能来自：\n"
            "- 普通子任务循环达到 max_inner_steps 仍未通过\n"
            "- 门禁任务 pytest 失败（观测以 [门禁失败] 开头，包含 gate_id 和 test_file）\n"
            "- LLM 终判认为当前方案走不通（needs_replan）\n\n"
            "输出一个 JSON 数组，包含修复任务 + 门禁重验任务（如果是门禁失败）。\n"
            "修复任务数量：\n"
            "- 如果 observation 中只有一个明确的错误根因 → 生成 1 个修复任务\n"
            "- 如果有多个独立的错误（不同函数、不同原因）→ 可生成多个修复任务，按依赖顺序排列\n"
            "- 如果多个错误可能源自同一个根因 → 只生成 1 个修复任务（修根因即可）\n\n"
            "每个任务对象字段：\n"
            "  id: 建议 replan-<模块>-<符号>，如 replan-memory-save\n"
            "  module: 被修复的模块类名\n"
            "  section: 对应 tech_doc 的 section 编号\n"
            "  symbol: 需要修复的函数/方法名\n"
            "  title: 简短描述修复目标\n"
            "  description: 详细说明要修什么、为什么（基于 observation）\n"
            "  target_file: 需要修改的产品代码文件路径\n"
            "  test_file: 对应的测试文件路径（如果知道）\n"
            "  done_criteria: 修复完成的验收标准（应具体到 pytest 哪个文件/断言通过）\n"
            "  task_kind: 'unit'（默认）或 'gate'（门禁重验任务）\n\n"
            "门禁失败时的处理：\n"
            "- 第一个任务：修复产品代码的子任务（task_kind='unit'）\n"
            "- 第二个任务：重新验证门禁（task_kind='gate'，复制原门禁的 id/test_file/pytest_scope 等）\n\n"
            "注意：\n"
            "- description 应包含 observation 中的关键错误信息\n"
            "- done_criteria 应尽量具体（如 'pytest test/unit/test_memory_save.py 通过'）\n"
            "- 如果 observation 指出是测试代码有问题而非产品代码，"
            "target_file 应指向测试文件\n\n"
            "只输出 JSON 数组，无 markdown。"
        )
        user = self._replan_user_prompt(observation, failed_task)
        try:
            text = chat(self._llm, system=system, user=user, harness_cfg=self.harness_cfg, agent_key="planner")
            # 尝试解析为数组（多个任务）
            try:
                from harness.llm_helpers import parse_json_array
                arr = parse_json_array(text)
            except (ValueError, Exception):
                # 回退：解析为单个对象
                arr = [parse_json_object(text)]

            fix_tasks: list[HarnessTask] = []
            for obj in arr:
                if not isinstance(obj, dict):
                    continue
                fix = HarnessTask(
                    id=str(obj.get("id", f"replan-{self._index}")),
                    order=10_000 + self._index + len(fix_tasks),
                    module=str(obj.get("module", "(replan)")),
                    section=str(obj.get("section", "replan")),
                    symbol=str(obj.get("symbol", "fix")),
                    title=str(obj.get("title", "replan 修正")),
                    description=str(obj.get("description", observation[:2000])),
                    dependencies=[],
                    target_file=str(obj.get("target_file", "")),
                    test_file=str(obj.get("test_file", "")),
                    done_criteria=str(obj.get("done_criteria", "evaluator 通过")),
                    task_kind=str(obj.get("task_kind", "unit")),
                )
                # 门禁重验任务需要保留 pytest_scope 等字段
                if obj.get("task_kind") == "gate":
                    if obj.get("pytest_scope"):
                        fix["pytest_scope"] = str(obj["pytest_scope"])
                    if obj.get("pytest_marker"):
                        fix["pytest_marker"] = str(obj["pytest_marker"])
                fix_tasks.append(fix)
            if fix_tasks:
                fix_tasks = self._normalize_fix_tasks(fix_tasks, state)
            return {"fix_tasks": fix_tasks} if fix_tasks else {"fix_tasks": []}
        except Exception:
            return {"fix_tasks": []}

    def node_fallback_replan(self, state: dict) -> dict:
        fixes = state.get("fix_tasks") or []
        if fixes:
            return {"fix_tasks": self._normalize_fix_tasks(fixes, state)}
        observation = state.get("observation", "")
        failed_task = state.get("failed_task")
        src_id = str((failed_task or {}).get("id", self._index))
        fix = HarnessTask(
            id=f"replan-{src_id}",
            order=10_000 + self._index,
            module=str((failed_task or {}).get("module") or "(replan)"),
            section=str((failed_task or {}).get("section") or "replan"),
            symbol=str((failed_task or {}).get("symbol") or "fix"),
            title=str((failed_task or {}).get("title") or "replan 修正任务"),
            description=f"根据观测修正上一任务：{observation[:2000]}",
            dependencies=[],
            target_file=str((failed_task or {}).get("target_file") or ""),
            test_file=str((failed_task or {}).get("test_file") or ""),
            done_criteria=str((failed_task or {}).get("done_criteria") or "evaluator 通过"),
        )
        return {"fix_tasks": self._normalize_fix_tasks([fix], state)}

    def node_append_replan(self, state: dict) -> dict:
        for t in state.get("fix_tasks") or []:
            self._queue.append(t)
        return {"fix_tasks": state.get("fix_tasks") or []}

    def apply_plan_result(self, final: dict) -> list[HarnessTask]:
        return list(final.get("tasks") or self._queue)
