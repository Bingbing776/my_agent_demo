"""Evaluator 业务逻辑（节点实现）；由 LangGraph 编排调用。"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from harness.config_loader import resolve_product_root
from harness.gates import (
    PYTEST_SCOPE_DIRECTORY,
    PYTEST_SCOPE_FILE,
    PYTEST_SCOPE_MARKER,
    collect_gate_pytest_paths,
    gate_allows_product_fix,
    is_gate_task,
    resolve_pytest_argv,
)
from harness.evaluator.function_calling import run_function_calling_loop
from harness.evaluator.tools import EvaluatorFileTools
from harness.llm_client import HarnessLLM, create_harness_llm
from harness.llm_http import HarnessCustomHttp, HarnessLLMHttpError, create_harness_custom_http
from harness.llm_helpers import chat, parse_json_object, strip_python_fence
from harness.planner.parsing import extract_spec_excerpt
from harness.project_context import build_project_context
from harness.test_index import (
    bootstrap_entries_from_tests,
    index_abs_path,
    list_test_functions,
    lookup_test_file,
    parse_entries,
    read_index,
    upsert_file_rows,
    write_index,
)
from harness.test_changelog import (
    append_test_change,
    changelog_abs_path,
    changelog_diff_max_chars,
)
from harness.test_progress import (
    ensure_progress_rows_for_test_code,
    infer_progress_from_eval,
    is_retry_exhausted,
    normalize_progress_icon,
    progress_abs_path,
    progress_note_for_exhaustion,
    sync_progress_from_index,
    upsert_task_progress,
)
from harness.integration_hints import collect_integration_hints, integration_hints_enabled
from harness.types import HarnessEvalResult, HarnessTask

logger = logging.getLogger(__name__)

TestWriteAction = str  # "skip" | "create" | "supplement" | "fix"


def _prompt_cap_from_config(config: dict, key: str, *, default: int | None = None) -> int | None:
    """evaluator 配置项：正整数=截断上限；0 或省略（且 default 为 None）= 不截断。"""
    if key not in config:
        return default
    try:
        v = int(config[key])
    except (TypeError, ValueError):
        return default
    return v if v > 0 else None


_FIXTURE_BY_CLASS: dict[str, str] = {
    "MemoryManager": "memory_manager",
    "ContextManager": "context_manager",
    "McpClient": "mcp_client",
    "Executor": "executor",
    "PlannerAgent": "planner_agent",
    "Evaluator": "evaluator",
    "Generator": "generator",
    "RagOrchestrator": "orchestrator",
}


class EvaluatorRuntime:
    """供 LangGraph 节点使用的 Evaluator 运行时。"""

    def __init__(
        self,
        config: dict | None = None,
        *,
        package_root: Path,
        harness_cfg: dict | None = None,
        llm: HarnessLLM | None = None,
        tech_doc_path: Path | None = None,
    ):
        """初始化 Evaluator：解析 product_root，按需创建 LLM、Custom HTTP、文件工具沙箱。"""
        self.config = config or {}
        self.harness_cfg = harness_cfg or {}
        self.package_root = package_root
        self.product_root = resolve_product_root(self.harness_cfg, package_root)
        self.max_pytest_seconds = int(self.config.get("pytest_timeout_sec", 120))
        self.tech_doc_path = tech_doc_path or (
            package_root / self.harness_cfg.get("tech_doc_path", "docs/tech_doc.md")
        )
        self._fc_max_rounds = int(self.config.get("fc_max_rounds", 8))

        self._llm: HarnessLLM | None = llm
        if self._llm is None and self._use_llm():
            self._llm = create_harness_llm(self.harness_cfg, package_root)

        self._llm_http: HarnessCustomHttp | None = None
        if self.config.get("use_function_calling", True):
            try:
                self._llm_http = create_harness_custom_http(
                    self.harness_cfg, package_root, agent_key="evaluator"
                )
            except HarnessLLMHttpError:
                if self.config.get("fc_require_custom_http", False):
                    raise
            except FileNotFoundError:
                if self.config.get("fc_require_custom_http", False):
                    raise

        self._file_tools = EvaluatorFileTools(
            product_root=self.product_root,
            package_root=self.package_root,
            max_file_chars=_prompt_cap_from_config(
                self.config, "fc_read_file_max_chars", default=None
            ),
        )
        self._pytest_fail_hint: dict[str, str] = {}
        self._coverage_cache: dict[str, dict[str, Any]] = {}
        self._graph_app = None

    def _prompt_cap(self, key: str, *, default: int | None = None) -> int | None:
        return _prompt_cap_from_config(self.config, key, default=default)

    def _use_llm(self) -> bool:
        """全局与 evaluator 配置是否允许使用 LLM（终判、写测试等）。"""
        if self.harness_cfg.get("llm_enabled") is False:
            return False
        return self.config.get("use_llm", True)

    def _write_tests_enabled(self) -> bool:
        """是否允许 Evaluator 自动创建/补全/修正测试文件。"""
        return bool(self.config.get("write_tests", True)) and self._llm is not None

    def _coverage_cache_enabled(self) -> bool:
        return bool(self.config.get("skip_coverage_recheck_when_stable", True))

    def _coverage_cache_key(self, task: HarnessTask) -> str:
        return str(task.get("id", "")).strip()

    def _test_path_mtime(self, task: HarnessTask) -> float | None:
        rel = str(task.get("test_file", "")).strip().replace("\\", "/")
        if not rel:
            probe = dict(task)
            self.apply_index_to_task(probe)
            rel = str(probe.get("test_file", "")).strip().replace("\\", "/")
        if not rel:
            return None
        path = self.product_root / rel
        if path.is_file():
            return path.stat().st_mtime
        if path.is_dir():
            mtimes = [p.stat().st_mtime for p in path.rglob("test_*.py") if p.is_file()]
            return max(mtimes) if mtimes else path.stat().st_mtime
        return None

    def _get_cached_coverage(self, task: HarnessTask) -> tuple[TestWriteAction, str] | None:
        if not self._coverage_cache_enabled():
            return None
        key = self._coverage_cache_key(task)
        if not key:
            return None
        cached = self._coverage_cache.get(key)
        if not cached or cached.get("action") != "skip":
            return None
        rel = str(task.get("test_file") or cached.get("test_file") or "").strip()
        if rel:
            task["test_file"] = rel.replace("\\", "/")
        mtime = self._test_path_mtime(task)
        if mtime is None:
            return None
        if mtime > float(cached.get("test_mtime", 0)):
            return None
        logger.info(
            "Evaluator coverage 缓存命中 task=%s test_file=%s",
            key,
            task.get("test_file"),
        )
        return str(cached["action"]), str(cached.get("reason", ""))

    def _store_coverage_cache(
        self, task: HarnessTask, action: TestWriteAction, reason: str
    ) -> None:
        key = self._coverage_cache_key(task)
        if not key:
            return
        if action != "skip":
            self._coverage_cache.pop(key, None)
            return
        if not self._coverage_cache_enabled():
            return
        mtime = self._test_path_mtime(task)
        if mtime is None:
            return
        self._coverage_cache[key] = {
            "action": action,
            "reason": reason,
            "test_file": str(task.get("test_file", "")).replace("\\", "/"),
            "test_mtime": mtime,
        }

    def _fc_mode(self) -> str:
        """Function calling 模式：native / json / auto。"""
        return str(self.config.get("fc_mode", "auto")).strip().lower()

    def _fc_fallback_json(self) -> bool:
        """auto 模式下原生 FC 失败时是否回退 JSON 协议。"""
        if self._fc_mode() == "native":
            return False
        if self._fc_mode() == "json":
            return True
        return bool(self.config.get("fc_fallback_json", True))

    def _use_function_calling(self) -> bool:
        """当前配置下是否走 function calling（读文件判完备性、写测试）。"""
        if not self.config.get("use_function_calling", True):
            return False
        if self._fc_mode() == "native":
            return self._llm_http is not None
        if self._fc_mode() == "json":
            return self._llm is not None
        return self._llm_http is not None or self._llm is not None

    def _run_fc_loop(self, **kwargs: Any) -> dict[str, Any]:
        """调用 function_calling 多轮循环，返回 LLM 的 final 对象（dict）。"""
        return run_function_calling_loop(
            http=self._llm_http,
            bundle=self._llm,
            harness_cfg=self.harness_cfg,
            agent_key="evaluator",
            max_rounds=self._fc_max_rounds,
            fc_mode=self._fc_mode(),
            fallback_json=self._fc_fallback_json(),
            **kwargs,
        )

    def _index_path(self) -> Path:
        """agent_rag 下 TEST_INDEX.md 的绝对路径。"""
        return index_abs_path(self.product_root, self.harness_cfg, self.config)

    def _progress_path(self) -> Path:
        """agent_rag 下 TEST_PROGRESS.md 的绝对路径。"""
        return progress_abs_path(self.product_root, self.harness_cfg, self.config)

    def _test_progress_enabled(self) -> bool:
        """是否在本轮评估结束时更新 TEST_PROGRESS.md。"""
        return bool(self.config.get("test_progress_update", True))

    def _changelog_path(self) -> Path:
        """agent_rag 下 TEST_CHANGELOG.md 的绝对路径。"""
        return changelog_abs_path(self.product_root, self.harness_cfg, self.config)

    def _test_changelog_enabled(self) -> bool:
        """Evaluator 改写测试文件后是否追加 TEST_CHANGELOG.md。"""
        return bool(self.config.get("test_changelog_update", True))

    def _load_index_entries(self, *, bootstrap_if_empty: bool = True) -> list[dict[str, str]]:
        """读取并解析 TEST_INDEX 表格行；索引为空时可从现有测试文件引导生成。"""
        path = self._index_path()  # 确定文件在哪
        text = read_index(path) # 读取 TEST_INDEX.md 的文本
        entries = parse_entries(text) # 解析文本，每行变成一条 dict
        if bootstrap_if_empty and len(entries) < 1:
            entries = bootstrap_entries_from_tests(self.product_root) # 从现有测试文件引导生成
            write_index(path, entries) # 写入 TEST_INDEX.md
        return entries

    def apply_index_to_task(self, task: HarnessTask) -> str | None:
        """
        仅根据 TEST_INDEX.md 为子任务解析 test_file 并写回 task。
        Planner 不再猜测路径；索引无匹配行时清空 test_file。
        """
        entries = self._load_index_entries()
        rel = lookup_test_file(entries, task)
        if rel:
            task["test_file"] = rel.replace("\\", "/")
            return task["test_file"]
        task["test_file"] = ""
        return None

    def full_test_index_catalog(self) -> str:
        """返回 TEST_INDEX 全文供 LLM prompt；test_index_catalog_max_chars>0 时才截断。"""
        text = read_index(self._index_path())
        return self._truncate_text(text, self._prompt_cap("test_index_catalog_max_chars", default=None))

    def _infer_test_path(self, task: HarnessTask) -> str | None:
        """根据任务信息推断测试文件的相对路径（relative to product_root）。

        推断优先级：
        1. target_class 在 _FIXTURE_BY_CLASS 中有映射 → 用映射的 prefix
        2. 从 target_file 的文件名提取 prefix
        3. 从 module 字段提取 prefix
        如果以上都无法推断，返回 None。

        路径格式：test/unit/test_{prefix}_{symbol}.py
        """
        # 1. 从 target_class 推断 prefix
        target_class = str(task.get("target_class", "")).strip()
        prefix: str | None = None
        if target_class and target_class in _FIXTURE_BY_CLASS:
            prefix = _FIXTURE_BY_CLASS[target_class]

        # 2. 从 target_file 推断 prefix
        if not prefix:
            target_file = str(task.get("target_file", "")).replace("\\", "/").strip()
            if target_file:
                # 取文件名去掉 .py，如 "agent_rag/memory/manager.py" → "manager"
                stem = Path(target_file).stem
                if stem and stem != "__init__":
                    prefix = stem
                else:
                    # __init__.py → 用父目录名
                    parent_name = Path(target_file).parent.name
                    if parent_name and parent_name not in (".", "agent_rag"):
                        prefix = parent_name

        # 3. 从 module 推断 prefix
        if not prefix:
            module = str(task.get("module", "")).strip()
            if module:
                # 取最后一段，如 "memory.manager" → "manager"
                prefix = module.rsplit(".", 1)[-1]

        if not prefix:
            return None

        # 拼接 symbol
        symbol = str(task.get("symbol", "")).strip()
        # 清理 symbol 中不适合作文件名的字符
        if symbol:
            clean_symbol = re.sub(r"[^a-zA-Z0-9_]", "_", symbol).strip("_")
            if clean_symbol:
                filename = f"test_{prefix}_{clean_symbol}.py"
            else:
                filename = f"test_{prefix}.py"
        else:
            filename = f"test_{prefix}.py"

        return f"test/unit/{filename}"

    def test_path(self, task: HarnessTask) -> Path | None:
        """解析当前子任务对应测试文件的绝对路径；无 test_file 则 None。"""
        self.apply_index_to_task(task)
        rel = task.get("test_file")
        if not rel:
            return None
        return self.product_root / str(rel)

    def read_test_file(self, path: Path | None) -> str:
        """读取测试文件文本；路径无效返回空串。"""
        if path is None or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _truncate_text(text: str, max_chars: int | None) -> str:
        if max_chars is None or len(text) <= max_chars:
            return text
        return text[: max_chars - 20] + "\n…[截断]\n"

    def read_impl_snippet(
        self, task: HarnessTask, draft_text: str, max_chars: int | None = None
    ) -> str:
        """拼实现文件（若已落盘）与 Generator 草稿，供 LLM 评估参考；默认不截断。"""
        if max_chars is not None:
            cap = max_chars if max_chars > 0 else None
        else:
            cap = self._prompt_cap("impl_snippet_max_chars", default=None)
        parts: list[str] = []
        target = task.get("target_file")
        if target:
            p = self.package_root / str(target)
            if p.is_file():
                body = p.read_text(encoding="utf-8", errors="replace")
                parts.append(
                    f"=== 已落盘实现 {target} ===\n"
                    f"{self._truncate_text(body, cap)}"
                )
        if draft_text.strip() and not draft_text.startswith("[stub]"):
            label = "Generator 草稿" if cap is None else "Generator 草稿（节选）"
            parts.append(
                f"=== {label} ===\n{self._truncate_text(draft_text, cap)}"
            )
        return "\n\n".join(parts) if parts else "（尚无实现文件或草稿；可用 read_file 查看实现）"

    def node_quick_rule(self, state: dict) -> dict:
        """LangGraph 节点：Generator 轨迹连续 [error] 达阈值则 hard_fail，短路后续流程。"""
        task = state["task"]
        trace = state.get("tool_trace_summary", "")
        streak = int(self.config.get("quick_rule_error_streak", 3))
        if trace.count("[error]") >= streak:
            return {
                "hard_fail": True,
                "eval_result": HarnessEvalResult(
                    passed=False,
                    score=0.0,
                    require_more_tools=False,
                    status="hard_fail",
                    issues=f"连续 {streak} 次 [error]",
                ),
                "progress_icon": "❌",
                "progress_note": f"quick_rule: 连续 {streak} 次 [error]",
            }
        return {"hard_fail": False}

    def node_apply_index(self, state: dict) -> dict:
        """LangGraph 节点：从 TEST_INDEX 补全 task.test_file，并可选预同步 TEST_PROGRESS。"""
        task = dict(state["task"])  # 拷贝子任务，避免直接改 LangGraph 里的原 dict
        self.apply_index_to_task(task)  # 根据 TEST_INDEX.md，确定「这个子任务应该跑/看哪个测试文件」，写进 task["test_file"]
        sync_note = ""
        if self._test_progress_enabled():  # "是否在本轮评估结束时更新 TEST_PROGRESS.md
            try:
                entries = self._load_index_entries()  # 扫描索引表TEST_INDEX.md，每行变成一条 dict
                sync_note = sync_progress_from_index(  # 同步 TEST_PROGRESS.md
                    self._progress_path(),  # TEST_PROGRESS.md 的绝对路径
                    entries,  # 索引表TEST_INDEX.md 每行变成的 dict
                    product_root=self.product_root,  # product_root 是项目根目录
                    harness_cfg=self.harness_cfg,  # harness_cfg 是harness.yaml 的配置
                    evaluator_cfg=self.config,  # evaluator_cfg 是evaluator.yaml 的配置
                )
            except Exception as e:
                sync_note = f"TEST_PROGRESS 预同步失败: {e}"
        return {"task": task, "progress_sync_note": sync_note}

    def node_assess_and_ensure_tests(self, state: dict) -> dict:
        """LangGraph 节点：LLM/规则判断测试完备性，必要时创建或改写测试文件。"""
        task = state["task"]
        draft = state.get("draft_text", "")
        gate = is_gate_task(task)
        # 任务级别禁止写测试（如 gate.1 的测试已手动确认完备）
        if task.get("skip_write_tests"):
            return {
                "test_note": "任务配置 skip_write_tests=true，跳过测试写入",
                "test_action": "skip",
                "test_reason": "task_skip_write_tests",
                "tests_just_updated": False,
            }
        if gate and not self._write_tests_enabled():
            return {
                "test_note": "门禁任务：write_tests 关闭，仅跑 pytest，不评估/改写测试",
                "test_action": "skip",
                "test_reason": "gate_write_disabled",
                "tests_just_updated": False,
            }
        if not gate and not self._write_tests_enabled():  # 是否允许 Evaluator 自动创建/补全/修正测试文件（evaluator.yaml 里的 write_tests 配置项）
            return {
                "test_note": "",
                "test_action": "skip",
                "test_reason": "",
                "tests_just_updated": False,
            }

        cached = self._get_cached_coverage(task)
        if cached is not None:
            action, reason = cached
            prefix = "门禁：" if gate else ""
            return {
                "test_note": f"{prefix}测试已完备（coverage 缓存）: {reason}",
                "test_action": action,
                "test_reason": reason,
                "tests_just_updated": False,
            }

        action, reason = self.decide_test_action(task, draft, gate=gate)
        self._store_coverage_cache(task, action, reason)
        prefix = "门禁：" if gate else ""
        if action == "skip":
            return {
                "test_note": f"{prefix}测试已完备，跳过: {reason}",
                "test_action": action,
                "test_reason": reason,
                "tests_just_updated": False,
            }

        if gate:
            ok, note = self.write_gate_test_files(task, draft, action=action, reason=reason)
        else:
            ok, note = self.write_test_file(task, draft, action=action, reason=reason)
        return {
            "test_note": note if ok else note,
            "test_action": action,
            "test_reason": reason,
            "tests_just_updated": ok and action in ("create", "supplement", "fix"),
        }

    def node_rule_evaluate(self, state: dict) -> dict:
        """LangGraph 节点：不用 LLM，纯靠"跑 pytest + 看文件存不存在"来给一个初步判断。"""
        task = state["task"]
        draft = state.get("draft_text", "")
        rule_result, pytest_out = self.rule_evaluate(task, draft)
        tid = str(task.get("id", ""))
        if rule_result.get("passed"):
            self._pytest_fail_hint.pop(tid, None)
        elif pytest_out:
            self._pytest_fail_hint[tid] = pytest_out

        test_note = state.get("test_note", "")
        if test_note and not rule_result.get("passed"):
            issues = rule_result.get("issues", "")
            rule_result = dict(rule_result)
            rule_result["issues"] = f"{issues}; {test_note}".strip("; ")[:2000]

        return {"rule_result": rule_result, "pytest_out": pytest_out}

    def node_llm_evaluate(self, state: dict) -> dict:
        """LangGraph 节点：在规则/pytest 结果上用 LLM 终判 passed、status、progress。"""
        if not self._llm:
            return {"eval_result": state["rule_result"]}
        result, icon, note = self.llm_evaluate(
            state["task"],
            state.get("tool_trace_summary", ""),
            state.get("draft_text", ""),
            state["rule_result"],
            state.get("pytest_out", ""),
            tests_just_updated=bool(state.get("tests_just_updated")),
            test_note=str(state.get("test_note", "")),
        )
        return {"eval_result": result, "progress_icon": icon, "progress_note": note}

    def node_merge_rule_only(self, state: dict) -> dict:
        """LangGraph 节点：无 LLM 时仅用 rule_result 推断 eval_result 与 progress。"""
        rule = state["rule_result"]
        trace = state.get("tool_trace_summary", "")
        icon = infer_progress_from_eval(
            rule,
            tests_just_updated=bool(state.get("tests_just_updated")),
            harness_cfg=self.harness_cfg,
            evaluator_cfg=self.config,
            tool_trace_summary=trace,
        )
        note = progress_note_for_exhaustion(
            rule, harness_cfg=self.harness_cfg, evaluator_cfg=self.config
        ) or str(rule.get("issues", ""))[:500]
        return {
            "eval_result": rule,
            "progress_icon": icon,
            "progress_note": note,
        }

    def node_update_test_progress(self, state: dict) -> dict:
        """LangGraph 节点：将评估结论写入 TEST_PROGRESS.md 对应子任务行。"""
        if not self._test_progress_enabled():
            return {}
        task = state["task"]
        eval_result = (
            state.get("eval_result")
            or state.get("rule_result")
            or HarnessEvalResult(
                passed=False,
                score=0.0,
                require_more_tools=True,
                status="ok",
                issues="",
            )
        )
        trace = state.get("tool_trace_summary", "")
        icon = state.get("progress_icon")
        if not icon:
            icon = infer_progress_from_eval(
                eval_result,
                tests_just_updated=bool(state.get("tests_just_updated")),
                harness_cfg=self.harness_cfg,
                evaluator_cfg=self.config,
                tool_trace_summary=trace,
            )
        if is_retry_exhausted(
            eval_result,
            harness_cfg=self.harness_cfg,
            evaluator_cfg=self.config,
            tool_trace_summary=trace,
        ):
            icon = "❌"
        note_parts = []
        cfg_note = progress_note_for_exhaustion(
            eval_result, harness_cfg=self.harness_cfg, evaluator_cfg=self.config
        )
        if cfg_note:
            note_parts.append(cfg_note)
        if state.get("progress_note"):
            note_parts.append(str(state["progress_note"]))
        if state.get("test_note"):
            note_parts.append(str(state["test_note"]))
        issues = str(eval_result.get("issues", ""))
        if issues and issues not in " ".join(note_parts):
            note_parts.append(issues)
        note = "; ".join(p for p in note_parts if p)[:500]

        try:
            entries = self._load_index_entries()
            msg = upsert_task_progress(
                self._progress_path(),
                task,
                icon=str(icon),
                note=note,
                index_entries=entries,
                harness_cfg=self.harness_cfg,
                evaluator_cfg=self.config,
                product_root=self.product_root,
            )
            return {"progress_sync_note": msg}
        except Exception as e:
            return {"progress_sync_note": f"TEST_PROGRESS 更新失败: {e}"}

    def decide_test_action(
        self, task: HarnessTask, draft_text: str, *, gate: bool = False
    ) -> tuple[TestWriteAction, str]:
        """决定测试操作：skip / create / supplement / fix（FC、简单 LLM 或规则回退）。"""
        gate = gate or is_gate_task(task)
        if not task.get("test_file") and not self.test_path(task):
            # 索引中无匹配，尝试推断路径并创建
            inferred = self._infer_test_path(task)
            if inferred is None:
                return "skip", "无 test_file 且无法推断路径（缺少 target_file/target_class/module）"
            task["test_file"] = inferred
            return "create", f"索引无匹配，自动推断 test_file={inferred}，需新建测试"

        if self._use_function_calling():
            return self.llm_assess_test_coverage_fc(task, draft_text, gate=gate)

        if self._llm is not None:
            return self.llm_assess_test_coverage_simple(task, draft_text, gate=gate)

        if gate:
            files = self._collect_gate_write_targets(task)
            chunks = [
                self.read_test_file(self.product_root / rel)
                for rel in files[:8]
            ]
            return self.fallback_assess_test(task, "\n\n".join(chunks))

        path = self.test_path(task)
        test_code = self.read_test_file(path) if path else ""
        return self.fallback_assess_test(task, test_code)

    @staticmethod
    def _gate_assess_prompt_extra(task: HarnessTask) -> str:
        scope = str(task.get("pytest_scope", PYTEST_SCOPE_FILE))
        marker = str(task.get("pytest_marker", "") or "").strip()
        rel = str(task.get("test_file", "")).replace("\\", "/")
        parts = [
            "\n\n【门禁任务】",
            f"pytest 范围: test_file={rel!r} scope={scope}",
        ]
        if marker:
            parts.append(f" marker={marker!r}")
        if gate_allows_product_fix(task):
            tf = str(task.get("target_file", "")).replace("\\", "/")
            globs = task.get("regression_test_globs") or []
            parts.append(
                f"。可修改产品实现 {tf!r}、门禁测试及 test/conftest；"
                f"修改产品后 Evaluator 会跑门禁测试与本节 unit 测试（{', '.join(globs) or '见 regression_test_globs'}）。"
                "勿新建无关 section 的单测。"
            )
        else:
            parts.append(
                "。仅评估/修改该范围内的测试及 test/helpers（契约门禁含 test/contracts，功能门禁含 test/gates）；"
                "勿新建无关 unit 单测，勿改 agent_rag 产品实现。"
            )
        parts.append(
            "若用例仍为 pytest.skip 占位且 done_criteria 要求真实验收，"
            "coverage 应为 incomplete 或 wrong，action 为 supplement 或 fix。"
        )
        return "".join(parts)

    def _collect_gate_write_targets(self, task: HarnessTask) -> list[str]:
        """门禁任务可写入的测试文件相对路径列表（单文件 / 目录 / marker）。"""
        rel = str(task.get("test_file", "")).replace("\\", "/").strip()
        if not rel:
            return []
        scope = str(task.get("pytest_scope", PYTEST_SCOPE_FILE)).strip().lower()
        path = self.product_root / rel.rstrip("/")

        if scope == PYTEST_SCOPE_FILE or path.is_file():
            return [rel] if path.is_file() else []

        if scope == PYTEST_SCOPE_DIRECTORY:
            if not path.is_dir():
                return []
            return sorted(
                str(p.relative_to(self.product_root)).replace("\\", "/")
                for p in path.rglob("test_*.py")
            )

        if scope == PYTEST_SCOPE_MARKER:
            marker = str(task.get("pytest_marker", "") or "").strip()
            base = path if path.is_dir() else path.parent
            if not base.is_dir():
                return []
            out: list[str] = []
            needle = f"pytest.mark.{marker}" if marker else ""
            for p in sorted(base.rglob("test_*.py")):
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if not needle or needle in text:
                    out.append(str(p.relative_to(self.product_root)).replace("\\", "/"))
            return out

        return []

    def write_gate_test_files(
        self,
        task: HarnessTask,
        draft_text: str,
        *,
        action: TestWriteAction,
        reason: str,
    ) -> tuple[bool, str]:
        """门禁：在 pytest 范围内对一个或多个测试文件执行 write_test_file。"""
        targets = self._collect_gate_write_targets(task)
        if not targets:
            return (
                False,
                f"门禁：评估为 {action}（{reason[:200]}），但无法解析可写测试路径 "
                f"(scope={task.get('pytest_scope')!r}, test_file={task.get('test_file')!r})",
            )
        notes: list[str] = []
        any_ok = False
        for rel in targets:
            sub: HarnessTask = dict(task)
            sub["test_file"] = rel
            sub["pytest_scope"] = PYTEST_SCOPE_FILE
            ok, note = self.write_test_file(sub, draft_text, action=action, reason=reason)
            any_ok = any_ok or ok
            notes.append(f"{rel}: {note}")
        return any_ok, "; ".join(notes)

    def llm_assess_test_coverage_fc(
        self, task: HarnessTask, draft_text: str, *, gate: bool = False
    ) -> tuple[TestWriteAction, str]:
        """用 function calling 读测试源码，返回完备性对应的 action 与 reasons。"""
        assert self._llm is not None
        symbol = str(task.get("symbol", ""))
        tid = str(task.get("id", ""))
        spec = self._spec_excerpt(task)
        pytest_hint = self._pytest_fail_hint.get(tid, "")
        index_catalog = self.full_test_index_catalog()
        hint_path = str(task.get("test_file") or "（请从 TEST_INDEX 定位）")
        if gate:
            targets = self._collect_gate_write_targets(task)
            if targets:
                hint_path = f"{hint_path}（范围内测试文件: {', '.join(targets[:12])}"
                if len(targets) > 12:
                    hint_path += f" …共{len(targets)}个"
                hint_path += "）"

        system = (
            "你是 Harness Evaluator Agent。根据 TEST_INDEX 目录定位当前子任务的 test_file，"
            "使用 read_file 自行读取测试源码、conftest、helpers 等，判断测试是否完备。\n"
            "不要猜测未读过的文件内容。\n\n"
            "注意：产品代码的实现摘要已在下方提供，通常无需再 read_file 读取产品源码，"
            "除非你确实需要查看摘要中未包含的细节。\n\n"
            "重要：若测试函数体仅为 pytest.skip(...) 占位，不算有效测试，"
            "coverage 应为 incomplete 或 wrong，action 为 supplement 或 fix。\n\n"
            "禁止为了让 pytest 通过而降低断言标准。测试断言必须反映 done_criteria 和规格要求，"
            "如果产品代码不满足断言，应保持断言不变——这说明产品代码需要修复，而不是测试需要放水。\n\n"
            "最终 final 对象字段：\n"
            '  "coverage": "complete" | "incomplete" | "wrong" | "missing"\n'
            '  "action": "skip" | "supplement" | "fix" | "create"\n'
            '  "reasons": "简短中文"\n'
            "coverage→action: complete→skip, incomplete→supplement, wrong→fix, missing→create"
        )
        if gate:
            system += self._gate_assess_prompt_extra(task)
        user_parts = [
            f"## 子任务\nid={tid} symbol=`{symbol}`\n"
            f"说明: {task.get('description')}\n"
            f"完成标准: {task.get('done_criteria')}\n"
            f"目标实现: {task.get('target_file')}\n"
            f"索引提示 test_file: {hint_path}\n",
            f"## TEST_INDEX 完整目录\n{index_catalog}\n",
            f"## 规格摘录\n{spec}\n",
            f"## 实现摘要（可用 read_file 读完整实现）\n{self.read_impl_snippet(task, draft_text)}\n",
            "建议至少 read_file: 本任务 test_file、test/conftest.py（若用到 fixture）。",
        ]
        if pytest_hint:
            hint = self._truncate_text(
                pytest_hint,
                self._prompt_cap("prompt_pytest_hint_max_chars", default=None),
            )
            user_parts.append(f"## 上轮 pytest 失败\n{hint}\n")
        user = "\n".join(user_parts)

        def _parse_final(obj: dict[str, Any]) -> dict[str, Any]:
            return obj

        try:
            obj = self._run_fc_loop(
                system=system,
                user=user,
                tools=self._file_tools,
                parse_final=_parse_final,
            )
            return self._map_coverage_to_action(obj)
        except Exception as e:
            return "supplement", f"FC 完备性检查失败: {e}"

    def llm_assess_test_coverage_simple(
        self, task: HarnessTask, draft_text: str, *, gate: bool = False
    ) -> tuple[TestWriteAction, str]:
        """无 FC：将索引中的测试片段打入 prompt，单次 chat 判断 coverage/action。"""
        assert self._llm is not None
        from harness.test_index import load_indexed_test_code

        symbol = str(task.get("symbol", ""))
        tid = str(task.get("id", ""))
        spec = self._spec_excerpt(task)
        entries = self._load_index_entries()
        indexed_code, files_loaded = load_indexed_test_code(
            self.product_root,
            entries,
            task,
            fallback_test_file=str(task.get("test_file") or "") or None,
        )
        if gate and not files_loaded:
            rels = self._collect_gate_write_targets(task)
            chunks: list[str] = []
            for rel in rels[:10]:
                p = self.product_root / rel
                if p.is_file():
                    chunks.append(
                        f"### {rel}\n```python\n{p.read_text(encoding='utf-8', errors='replace')[:30000]}\n```"
                    )
                    files_loaded.append(rel)
            if chunks:
                indexed_code = "\n\n".join(chunks)
        system = (
            "你是 Harness Evaluator Agent。根据 TEST_INDEX 与下方测试片段判断测试完备性。\n"
            "只输出 JSON 对象，字段：\n"
            '  "coverage": "complete" | "incomplete" | "wrong" | "missing"\n'
            '  "action": "skip" | "supplement" | "fix" | "create"\n'
            '  "reasons": "简短中文说明"\n\n'
            "重要：若测试函数体仅为 pytest.skip(...) 占位，不算有效测试，"
            "coverage 应为 incomplete 或 wrong，action 为 supplement 或 fix。\n\n"
            "禁止为了让 pytest 通过而降低断言标准。测试断言必须反映 done_criteria 和规格要求，"
            "如果产品代码不满足断言，应保持断言不变——这说明产品代码需要修复，而不是测试需要放水。\n\n"
            "coverage 含义：\n"
            "  complete — 测试已覆盖 done_criteria 所有场景，无需修改\n"
            "  incomplete — 测试存在但缺少部分场景\n"
            "  wrong — 测试存在但断言有误或与实现不匹配\n"
            "  missing — 无测试文件或无 test_ 函数"
        )
        if gate:
            system += self._gate_assess_prompt_extra(task)
        user = (
            f"子任务 id={tid} symbol={symbol}\n"
            f"TEST_INDEX:\n{self.full_test_index_catalog()}\n\n"
            f"测试片段（{files_loaded}）:\n{indexed_code}\n\n"
            f"规格:\n{spec}\n\n"
            f"实现:\n{self.read_impl_snippet(task, draft_text)}"
        )
        try:
            raw = chat(
                self._llm,
                system=system,
                user=user,
                harness_cfg=self.harness_cfg,
                agent_key="evaluator",
            )
            return self._map_coverage_to_action(parse_json_object(raw))
        except Exception as e:
            return "supplement", f"LLM 完备性检查失败: {e}"

    def _map_coverage_to_action(self, obj: dict[str, Any]) -> tuple[TestWriteAction, str]:
        """将 LLM 返回的 coverage/action 规范化为 skip/create/supplement/fix。"""
        coverage = str(obj.get("coverage", "")).lower()
        action = str(obj.get("action", "")).lower()
        reasons = str(obj.get("reasons", ""))[:1000]
        cov_map = {
            "complete": "skip",
            "incomplete": "supplement",
            "wrong": "fix",
            "missing": "create",
        }
        if coverage in cov_map:
            action = cov_map[coverage]
        if action not in ("skip", "supplement", "fix", "create"):
            action = "supplement"
        return action, reasons or coverage

    def fallback_assess_test(self, task: HarnessTask, text: str) -> tuple[TestWriteAction, str]:
        """未启用 LLM 时对测试文本做极简规则判断。"""
        if not text.strip():
            return "create", "测试文件为空"
        if "def test_" not in text:
            return "create", "缺少 test_ 函数"
        return "supplement", "未启用 LLM，无法判断完备性"

    def write_test_file(
        self,
        task: HarnessTask,
        draft_text: str,
        *,
        action: TestWriteAction,
        reason: str,
    ) -> tuple[bool, str]:
        """生成测试源码、写入磁盘、同步 TEST_INDEX 与 TEST_PROGRESS，返回是否成功及说明。"""
        # 如果 test_file 已经是具体 .py 文件，直接使用，避免 apply_index_to_task 覆盖
        rel = str(task.get("test_file", "")).replace("\\", "/").strip()
        if rel.endswith(".py"):
            path = self.product_root / rel
        else:
            path = self.test_path(task)
        if path is None:
            # 兜底：decide_test_action 应已设置 test_file，这里再试一次推断
            inferred = self._infer_test_path(task)
            if inferred:
                task["test_file"] = inferred
                path = self.product_root / inferred
            else:
                return False, "无 test_file 且无法推断路径"
        if self._llm is None:
            return False, "未连接 LLM"

        path.parent.mkdir(parents=True, exist_ok=True)
        code = ""
        if self._use_function_calling():
            try:
                code = self._write_test_via_fc(task, draft_text, action=action, reason=reason)
                # 验证 FC 生成的代码语法是否正确
                if code:
                    import ast
                    try:
                        ast.parse(code)
                    except SyntaxError:
                        # FC 模式生成的代码有语法错误（常见于 JSON 转义问题），回退到 chat 模式
                        code = ""
            except (ValueError, Exception):
                # FC 模式失败（如 LLM 未返回 test_source），回退到 chat 模式
                code = ""
        if not code:
            code = self._write_test_via_chat(task, draft_text, action=action, reason=reason)

        if not code or "def test_" not in code:
            return False, "LLM 未生成 def test_ 函数"
        old_code = self.read_test_file(path) if path.is_file() else ""
        new_code = code.rstrip() + "\n"
        path.write_text(new_code, encoding="utf-8")
        rel = str(task.get("test_file", "")).replace("\\", "/")
        index_note = self.sync_test_index(task, rel, code, action=action)
        verb = {"create": "新建", "supplement": "补全", "fix": "修正"}.get(action, "更新")
        msg = f"{verb}测试 {rel}: {reason[:200]}"
        if index_note:
            msg += f"; {index_note}"
        if self._test_changelog_enabled():
            try:
                cl_note = append_test_change(
                    self._changelog_path(),
                    task,
                    test_rel=rel,
                    action=action,
                    reason=reason,
                    old_code=old_code,
                    new_code=new_code,
                    diff_max_chars=changelog_diff_max_chars(self.config),
                )
                msg += f"; {cl_note}"
            except Exception as e:
                msg += f"; TEST_CHANGELOG 写入失败: {e}"
        if self._test_progress_enabled():
            try:
                entries = self._load_index_entries(bootstrap_if_empty=True)
                progress_note = f"Evaluator {verb} 测试，待复测"
                msg += "; " + ensure_progress_rows_for_test_code(
                    self._progress_path(),
                    rel,
                    code,
                    task,
                    harness_cfg=self.harness_cfg,
                    evaluator_cfg=self.config,
                    default_icon="🔧",
                    note=progress_note,
                )
                msg += "; " + sync_progress_from_index(
                    self._progress_path(),
                    entries,
                    product_root=self.product_root,
                    harness_cfg=self.harness_cfg,
                    evaluator_cfg=self.config,
                    mark_test_file=rel,
                    mark_icon="🔧",
                    mark_note=progress_note,
                )
            except Exception as e:
                msg += f"; TEST_PROGRESS 同步失败: {e}"
        return True, msg

    def _write_test_via_fc(
        self, task: HarnessTask, draft_text: str, *, action: str, reason: str
    ) -> str:
        """FC 读现有测试后，让 LLM 在 final.test_source 中输出完整 pytest 源码。"""
        assert self._llm is not None
        class_name = str(task.get("target_class") or task.get("module", ""))
        import_path = self._guess_import_path(task)
        symbol = str(task.get("symbol", ""))
        # 根据测试文件路径决定 pytest mark
        test_rel = str(task.get("test_file", "")).replace("\\", "/")
        if "test/gates" in test_rel:
            mark_hint = "pytestmark = [pytest.mark.gate]"
        elif "test/integration" in test_rel:
            mark_hint = "pytestmark = [pytest.mark.integration]"
        elif "test/e2e" in test_rel:
            mark_hint = "pytestmark = [pytest.mark.e2e]"
        else:
            mark_hint = "pytestmark = [pytest.mark.unit]"
        guide = {
            "create": "【新建】输出完整 pytest 文件。",
            "supplement": "【补全】保留正确部分，补全 assert，去掉 pytest.skip('implement')。",
            "fix": f"【修正】{reason}，输出完整可运行文件。",
        }.get(action, "【补全】")

        system = (
            "你是 Harness Evaluator Agent。用 read_file 查看现有测试与 conftest，"
            "然后输出 final 对象：\n"
            '{"final": {"test_source": "完整 python 源码字符串"}}\n'
            f"不要 markdown 围栏。要求：pytest、{mark_hint}、实质 assert。\n"
            "禁止为了让 pytest 通过而降低断言标准——断言必须反映 done_criteria 要求，"
            "如果产品代码有 bug 导致测试失败，应保持正确的断言让 Generator 去修产品代码。\n"
            "建议用 read_file 查看 test/helpers/samples.py 获取真实业务数据（RAG 查询、MCP 返回、多轮对话等），"
            "用这些数据构造测试输入，而不是编造假数据。\n\n"
            "注意：产品代码的实现摘要已在下方提供，通常无需再 read_file 读取产品源码。\n\n"
            "重要（JSON 转义）：test_source 是 JSON 字符串值，Python 代码中字符串字面量里的换行"
            "必须写成 \\\\n（双重转义），否则 JSON 解析后会变成真正的换行导致语法错误。\n"
            '正确示例：{"final": {"test_source": "msg = \\"hello\\\\nworld\\""}}\n'
            '错误示例：{"final": {"test_source": "msg = \\"hello\\nworld\\""}}\n\n'
            "重要（编码）：test_source 中的注释、docstring 和字符串字面量必须使用英文，"
            "禁止使用中文或其他非 ASCII 字符，避免编码问题。\n\n"
            f"{guide}\n"
            f"导入: from {import_path} import {class_name}\n"
        )
        user = (
            f"子任务 id={task.get('id')} symbol={symbol} test_file={task.get('test_file')}\n"
            f"{self.fixture_hint(task)}\n\n"
            f"TEST_INDEX:\n{self.full_test_index_catalog()}\n\n"
            f"实现摘要:\n{self.read_impl_snippet(task, draft_text)}\n"
        )

        def _parse(obj: dict[str, Any]) -> dict[str, Any]:
            if "test_source" in obj:
                return obj
            inner = obj.get("final")
            if isinstance(inner, dict) and "test_source" in inner:
                return inner
            raise ValueError("missing test_source")

        obj = self._run_fc_loop(
            system=system,
            user=user,
            tools=self._file_tools,
            parse_final=_parse,
        )
        # 获取 test_source，它应该已经是正确解析的 Python 字符串
        test_source = obj.get("test_source", "")

        # 如果 test_source 不是字符串，转换为字符串
        if not isinstance(test_source, str):
            test_source = str(test_source)

        return strip_python_fence(test_source)

    def _write_test_via_chat(
        self, task: HarnessTask, draft_text: str, *, action: str, reason: str
    ) -> str:
        """单次 chat 根据索引片段与实现摘要生成 pytest 文件内容。"""
        from harness.test_index import load_indexed_test_code

        assert self._llm is not None
        entries = self._load_index_entries()
        indexed_existing, _ = load_indexed_test_code(
            self.product_root, entries, task,
            fallback_test_file=str(task.get("test_file") or "") or None,
        )
        class_name = str(task.get("target_class") or task.get("module", ""))
        import_path = self._guess_import_path(task)
        # 根据测试文件路径决定 pytest mark
        test_rel = str(task.get("test_file", "")).replace("\\", "/")
        if "test/gates" in test_rel:
            mark_line = "pytestmark = [pytest.mark.gate]"
        elif "test/integration" in test_rel:
            mark_line = "pytestmark = [pytest.mark.integration]"
        elif "test/e2e" in test_rel:
            mark_line = "pytestmark = [pytest.mark.e2e]"
        else:
            mark_line = "pytestmark = [pytest.mark.unit]"
        action_guide = {
            "create": "新建完整 pytest 文件，覆盖 done_criteria 中的所有场景。",
            "supplement": "在现有测试基础上补充缺失的测试用例，保留已有正确的 test_ 函数。",
            "fix": f"修正现有测试中的问题（{reason}），输出修正后的完整文件。",
        }.get(action, "补全测试用例。")
        system = (
            "你是 Harness Evaluator Agent，负责生成 pytest 测试文件。\n"
            "要求：\n"
            "1. 输出完整可运行的 Python 文件，不要 markdown 围栏\n"
            f"2. 文件顶部添加 {mark_line}\n"
            "3. 每个 test_ 函数必须包含实质性 assert（不允许 assert True 或 pytest.skip）\n"
            "4. 使用 conftest.py 中已有的 fixture（如有）\n"
            f"5. 导入被测对象: from {import_path} import {class_name}\n"
            "6. 禁止为了让 pytest 通过而降低断言标准——断言必须反映 done_criteria 要求，"
            "如果产品代码有 bug 导致测试失败，应保持正确的断言让 Generator 去修产品代码\n"
            "7. 优先使用 test/helpers/samples.py 中的真实业务数据（sample_rag_queries、"
            "sample_mcp_tool_call_result、sample_memory_conversation 等）构造测试输入\n\n"
            f"当前操作: {action} — {action_guide}"
        )
        user = (
            f"子任务: id={task.get('id')} symbol={task.get('symbol')}\n"
            f"完成标准: {task.get('done_criteria')}\n\n"
            f"## 现有测试（TEST_INDEX 匹配）\n{indexed_existing}\n\n"
            f"## 被测实现摘要\n{self.read_impl_snippet(task, draft_text)}"
        )
        raw = chat(self._llm, system=system, user=user, harness_cfg=self.harness_cfg, agent_key="evaluator")
        return strip_python_fence(raw)

    def sync_test_index(
        self, task: HarnessTask, test_rel: str, test_code: str, *, action: str
    ) -> str:
        """写测试后更新 TEST_INDEX.md（规则同步：提取 def test_* 函数名，upsert 对应行）。"""
        # 门禁任务不同步 INDEX——门禁区已有入口行，无需往 Unit 区插函数行
        if is_gate_task(task):
            return ""

        index_path = self._index_path()
        entries = self._load_index_entries(bootstrap_if_empty=True)
        class_name = str(task.get("target_class") or task.get("module") or "")
        symbol = str(task.get("symbol", ""))
        tid = str(task.get("id", ""))

        fns = list_test_functions(test_code)
        entries = upsert_file_rows(
            entries,
            test_file=test_rel,
            target_class=class_name,
            target_symbol=symbol,
            task_id=tid,
            test_functions=fns,
        )
        write_index(index_path, entries)
        return "已更新 TEST_INDEX.md"

    def rule_evaluate(
        self, task: HarnessTask, draft_text: str
    ) -> tuple[HarnessEvalResult, str]:
        """不依赖 LLM 的初判：pytest、gate、实现 def 是否存在、仅有草稿等。"""
        test_file = task.get("test_file")
        target_file = task.get("target_file")
        symbol = task.get("symbol", "")
        pytest_out = ""

        if test_file:
            ok, pytest_out = self.run_pytest_for_task(task)
            if ok is not None:
                if ok:
                    return (
                        HarnessEvalResult(
                            passed=True,
                            score=1.0,
                            require_more_tools=False,
                            status="ok",
                            issues="",
                        ),
                        pytest_out,
                    )
                return (
                    HarnessEvalResult(
                        passed=False,
                        score=0.3,
                        require_more_tools=not is_gate_task(task),
                        status="ok",
                        issues=pytest_out or "pytest 未通过",
                    ),
                    pytest_out,
                )

        if is_gate_task(task):
            return (
                HarnessEvalResult(
                    passed=False,
                    score=0.0,
                    require_more_tools=False,
                    status="hard_fail",
                    issues=f"门禁任务缺少可执行的 test_file: {test_file!r}",
                ),
                pytest_out,
            )

        if target_file and symbol:
            src = self.package_root / target_file
            if src.is_file() and f"def {symbol}" in src.read_text(encoding="utf-8", errors="replace"):
                return (
                    HarnessEvalResult(
                        passed=True,
                        score=0.7,
                        require_more_tools=False,
                        status="ok",
                        issues="无 pytest，仅检测到 def 存在",
                    ),
                    pytest_out,
                )
            return (
                HarnessEvalResult(
                    passed=False,
                    score=0.0,
                    require_more_tools=True,
                    status="ok",
                    issues=f"未找到 {target_file} 中的 def {symbol}",
                ),
                pytest_out,
            )

        if draft_text.strip() and not draft_text.startswith("[stub]"):
            return (
                HarnessEvalResult(
                    passed=False,
                    score=0.4,
                    require_more_tools=True,
                    status="ok",
                    issues="有草稿但未落盘或未通过测试",
                ),
                pytest_out,
            )

        return (
            HarnessEvalResult(
                passed=False,
                score=0.0,
                require_more_tools=True,
                status="ok",
                issues="无有效产出",
            ),
            pytest_out,
        )

    def llm_evaluate(
        self,
        task: HarnessTask,
        tool_trace_summary: str,
        draft_text: str,
        rule_result: HarnessEvalResult,
        pytest_out: str,
        *,
        tests_just_updated: bool = False,
        test_note: str = "",
    ) -> tuple[HarnessEvalResult, str, str]:
        """结合规则结果、pytest 输出与草稿做 LLM 终判，返回结果与 progress 图标/备注。"""
        assert self._llm is not None
        system = (
            "你是 Harness Evaluator Agent，负责对子任务实现做最终判定。\n"
            "综合 pytest 结果、规则初判、Generator 草稿和工具轨迹，判断实现是否完成。\n"
            "只输出 JSON，字段：\n"
            "  passed (bool): 实现是否满足 done_criteria\n"
            "  score (float 0~1): 完成度\n"
            "  require_more_tools (bool): Generator 是否还需要继续修改代码\n"
            "  status: ok — 正常（Generator 可继续循环）| needs_replan — 当前方案走不通需要 Planner 重新规划 | hard_fail — 不可恢复\n"
            "  issues (str): 具体问题描述，会传给 Generator 作为下轮修改的依据。"
            "应明确指出是产品代码的问题还是测试代码的问题\n"
            "  progress: 写入 TEST_PROGRESS.md 的状态图标\n"
            "  progress_note: 一行中文备注\n\n"
            "progress 必须为以下之一：\n"
            "  pass / ✅ — pytest 通过且实现满足 done_criteria\n"
            "  fail / ❌ — 已达重试上限仍失败"
            f"（max_inner_steps={int((self.harness_cfg.get('generator') or {}).get('max_inner_steps', 8))}，"
            f"quick_rule_error_streak={int(self.config.get('quick_rule_error_streak', 3))}）\n"
            "  skip / ⏭️ — 因缺少第三方 API Key 等无法执行\n"
            "  fix / 🔧 — 刚修改/补全测试或实现，待下轮复测\n"
            "  pending / ⬜ — 尚未有可靠结论\n\n"
            "判断原则：\n"
            "- pytest 通过不等于实现正确——需对照 done_criteria 确认测试覆盖了所有要求\n"
            "- pytest 失败时区分：是产品代码 bug（issues 应指出代码问题）还是测试本身有误（issues 应指出测试问题）\n"
            "- 如果测试断言不合理（与 done_criteria 矛盾），应在 issues 中说明测试需要修正，"
            "而不是判定产品代码需要迁就错误断言"
        )
        user_parts = [
            f"子任务 id={task.get('id')} symbol={task.get('symbol')}\n",
            f"目标={task.get('target_file')} test_file={task.get('test_file')}\n",
            f"标准={task.get('done_criteria')}\n",
            f"规则初判 passed={rule_result.get('passed')} issues={rule_result.get('issues')}\n",
            f"pytest:\n{self._truncate_text(pytest_out or '（无）', self._prompt_cap('prompt_pytest_max_chars', default=None))}\n",
            f"轨迹:\n{self._truncate_text(tool_trace_summary, self._prompt_cap('prompt_trace_max_chars', default=None))}\n",
            f"草稿:\n{self._truncate_text(draft_text, self._prompt_cap('prompt_draft_max_chars', default=None))}",
        ]
        if tests_just_updated:
            user_parts.append(
                f"\n注意：本轮 Evaluator 刚修改了测试文件: "
                f"{self._truncate_text(test_note, self._prompt_cap('prompt_test_note_max_chars', default=None))}\n"
                "上方 pytest 结果基于新测试运行，但新测试本身可能存在问题（断言不当、fixture 缺失等）。\n"
                "若无法确认实现已完全正确，progress 宜为 fix(🔧)，表示需要下轮再次验证。"
            )
        user = "\n".join(user_parts)
        try:
            text = chat(
                self._llm,
                system=system,
                user=user,
                harness_cfg=self.harness_cfg,
                agent_key="evaluator",
            )
            obj = parse_json_object(text)
            status = str(obj.get("status", "ok"))
            if status not in ("ok", "needs_replan", "hard_fail"):
                status = "ok"
            passed = bool(obj.get("passed", False))
            if status in ("needs_replan", "hard_fail"):
                passed = False
            result = HarnessEvalResult(
                passed=passed,
                score=float(obj.get("score", 0.0)),
                require_more_tools=bool(obj.get("require_more_tools", True)),
                status=status,
                issues=str(obj.get("issues", ""))[:2000],
            )
            icon = normalize_progress_icon(
                obj.get("progress") or obj.get("progress_icon"),
                passed=passed,
                status=status,
                tests_just_updated=tests_just_updated,
            )
            if is_retry_exhausted(
                result,
                harness_cfg=self.harness_cfg,
                evaluator_cfg=self.config,
                tool_trace_summary=tool_trace_summary,
            ):
                icon = "❌"
            note = str(obj.get("progress_note", ""))[:500]
            ex_note = progress_note_for_exhaustion(
                result, harness_cfg=self.harness_cfg, evaluator_cfg=self.config
            )
            if ex_note:
                note = f"{ex_note}; {note}" if note else ex_note
            if not note:
                note = str(result.get("issues", ""))[:500]
            return result, icon, note
        except Exception as e:
            rule_copy = dict(rule_result)
            rule_copy["issues"] = f"{rule_copy.get('issues', '')}; LLM评估失败: {e}"[:2000]
            icon = infer_progress_from_eval(
                rule_copy,
                tests_just_updated=tests_just_updated,
                harness_cfg=self.harness_cfg,
                evaluator_cfg=self.config,
                tool_trace_summary=tool_trace_summary,
            )
            return rule_copy, icon, f"LLM评估失败: {e}"[:500]

    def _spec_excerpt(self, task: HarnessTask) -> str:
        """从 tech_doc.md 抽取当前子任务相关的接口规格片段。"""
        if not self.tech_doc_path.is_file():
            return ""
        doc = self.tech_doc_path.read_text(encoding="utf-8")
        cap = self._prompt_cap("write_tests_spec_max_chars", default=None)
        excerpt_max = cap if cap is not None else len(doc)
        return extract_spec_excerpt(
            doc,
            str(task.get("id", "")),
            str(task.get("symbol", "")),
            excerpt_max,
            target_class=str(task.get("target_class") or task.get("module", "")),
        )

    def _guess_import_path(self, task: HarnessTask) -> str:
        """根据 target_file / target_module 推断测试文件中的 import 模块路径。"""
        tf = str(task.get("target_file", ""))
        m = re.search(r"agent_rag/agent_rag/(.+)\.py$", tf.replace("\\", "/"))
        if m:
            return "agent_rag." + m.group(1).replace("/", ".")
        tm = str(task.get("target_module", ""))
        if tm.startswith("agent_rag."):
            return tm
        return f"agent_rag.{tm}" if tm else "agent_rag"

    def fixture_hint(self, task: HarnessTask) -> str:
        """返回写测试时建议使用的 conftest fixture 名称提示。"""
        cls = str(task.get("target_class") or task.get("module") or "")
        fix = _FIXTURE_BY_CLASS.get(cls)
        if fix:
            return f"优先使用 conftest fixture: `{fix}`"
        return "参考 test/conftest.py"

    def run_pytest(self, test_path: Path, *, extra_argv: list[str] | None = None) -> tuple[bool, str]:
        """对单个测试路径执行 pytest -q，返回是否通过与输出摘要。"""
        argv = [str(test_path)]
        if extra_argv:
            argv = list(extra_argv)
        cmd = [sys.executable, "-m", "pytest", *argv, "-q", "--tb=line"]
        return self._run_pytest_cmd(cmd)

    def run_pytest_for_task(self, task: HarnessTask) -> tuple[bool | None, str]:
        """
        按任务解析 pytest 目标。返回 (None, '') 表示路径不存在、未执行。
        允许改产品的门禁：一次跑 gate 测试 + 本节 regression_test_globs。
        """
        if gate_allows_product_fix(task):
            paths = collect_gate_pytest_paths(task, self.product_root)
            if not paths:
                return None, ""
            missing = [
                p
                for p in paths
                if not (self.product_root / p).is_file()
            ]
            if missing:
                return False, f"pytest 路径不存在: {', '.join(missing[:5])}"
            extra = list(task.get("pytest_extra_args") or [])
            cmd = [sys.executable, "-m", "pytest", *paths, *extra, "-q", "--tb=line"]
            return self._run_pytest_cmd(cmd)

        rel = str(task.get("test_file", "")).replace("\\", "/").strip()
        if not rel:
            return None, ""

        argv = resolve_pytest_argv(task, self.product_root)
        if not argv:
            return None, ""

        target = self.product_root / rel.rstrip("/")
        if str(task.get("pytest_scope", "file")) == "file" and not rel.endswith("/"):
            if not target.is_file():
                return None, ""
        elif not target.exists():
            return None, ""

        cmd = [sys.executable, "-m", "pytest", *argv]
        return self._run_pytest_cmd(cmd)

    def _run_pytest_cmd(self, cmd: list[str]) -> tuple[bool, str]:
        """在 product_root 下子进程执行 pytest 命令，处理超时与输出截断。"""
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.product_root),
                capture_output=True,
                text=True,
                timeout=self.max_pytest_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, "pytest 超时"
        out = (proc.stdout or "") + (proc.stderr or "")
        cap = self._prompt_cap("pytest_capture_max_chars", default=None)
        body = out.strip()
        if proc.returncode == 0:
            return True, self._truncate_text(body, cap) if body else ""
        return False, self._truncate_text(body, cap) if body else f"exit {proc.returncode}"

    def invalidate_context_cache(self) -> None:
        """子任务结束后清空 pytest 失败 hint 与 coverage 缓存。"""
        self._pytest_fail_hint.clear()
        self._coverage_cache.clear()

    def to_planner_observation(
        self,
        eval_result: HarnessEvalResult,
        max_chars: int | None = None,
        *,
        task: HarnessTask | None = None,
        step_count: int | None = None,
    ) -> str:
        """将评估结果转为结构化文本，供 Planner replan 使用。

        包含：任务信息、评估结论、具体问题、已尝试次数，
        让 Planner LLM 能做出精准的修复决策。
        """
        cap = max_chars if max_chars is not None else self._prompt_cap("eval_max_chars", default=None)
        parts: list[str] = []

        # 任务信息（如果有）
        if task:
            parts.append(
                f"子任务: id={task.get('id')} symbol={task.get('symbol')} "
                f"target_file={task.get('target_file')} test_file={task.get('test_file')}"
            )
            if task.get("done_criteria"):
                parts.append(f"完成标准: {task.get('done_criteria')}")

        # 评估结论
        parts.append(f"评估结果: passed={eval_result.get('passed')} status={eval_result.get('status')}")

        # 具体问题（最关键的信息）
        issues = eval_result.get("issues", "")
        if issues:
            parts.append(f"具体问题:\n{issues}")

        if task and integration_hints_enabled(self.harness_cfg):
            hint_text = collect_integration_hints(
                symbol=str(task.get("symbol") or ""),
                issues=str(issues or ""),
                target_file=str(task.get("target_file") or ""),
                primary_symbol=str(task.get("symbol") or ""),
            )
            if hint_text:
                parts.append(f"MODULAR 集成实现参考（供 replan / 下一轮 implement）：\n{hint_text}")

        # 已尝试次数
        if step_count is not None:
            parts.append(f"已尝试轮数: {step_count}/{self.config.get('quick_rule_error_streak', 3)}")

        text = "\n".join(parts)
        return self._truncate_text(text, cap)
