"""Generator 业务逻辑与 LangGraph 节点。"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.evaluator.agent import HarnessEvaluator
from harness.generator.code_merge import merge_all_methods_from_draft, merge_method_into_class
from harness.generator.draft_extract import (
    code_covers_symbol,
    draft_has_mergeable_product_defs,
    draft_looks_like_test_script,
    extract_code_from_draft,
    list_def_symbols,
    list_product_def_symbols,
    merged_preserves_target_class,
    method_in_target_class,
    prioritize_symbols,
)
from harness.integration_hints import (
    collect_integration_hints,
    integration_hints_enabled,
    needs_integration_hints,
)
from harness.gates import gate_allows_product_fix, is_gate_task
from harness.llm_client import HarnessLLM, create_harness_llm
from harness.llm_helpers import chat
from harness.project_context import build_project_context
from harness.types import HarnessEvalResult, HarnessSubtaskResult, HarnessTask

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    reason: str


class GeneratorRuntime:
    def __init__(
        self,
        config: dict | None = None,
        *,
        package_root: Path,
        tech_doc_path: Path,
        harness_cfg: dict | None = None,
        llm: HarnessLLM | None = None,
    ):
        self.config = config or {}
        self.package_root = package_root
        self.tech_doc_path = tech_doc_path
        self.harness_cfg = harness_cfg or {}
        self.max_inner_steps = int(self.config.get("max_inner_steps", 8))
        self._llm_bundle: HarnessLLM | None = llm
        if self._llm_bundle is None and self.harness_cfg.get("llm_enabled") is not False:
            self._llm_bundle = create_harness_llm(self.harness_cfg, package_root)

        self._project_context_cache: str | None = None
        self._evaluator: HarnessEvaluator | None = None
        self._subtask_graph_app = None

    def set_evaluator(self, evaluator: HarnessEvaluator) -> None:
        self._evaluator = evaluator

    def reset_subtask_state(self) -> None:
        pass

    def invalidate_context_cache(self) -> None:
        self._project_context_cache = None

    def _get_project_context(self) -> str:
        if self._project_context_cache is None:
            harness_cfg = {
                "implementation_root": self.config.get(
                    "implementation_root", "../agent_rag/agent_rag"
                ),
                "generator": self.config,
                "read_only_code_roots": self.config.get("read_only_code_roots"),
                "mcp_server_code_path": self.config.get("mcp_server_code_path"),
            }
            self._project_context_cache = build_project_context(
                package_root=self.package_root,
                tech_doc_path=self.tech_doc_path,
                harness_cfg=harness_cfg,
                tech_doc_max_chars=int(self.config.get("tech_doc_max_chars", 200_000)),
                total_code_max_chars=int(self.config.get("code_snapshot_max_chars", 300_000)),
            )
        return self._project_context_cache

    def _format_trace(self, inner_trace: list[dict[str, Any]]) -> str:
        if not inner_trace:
            return "（尚无步骤）"
        lines = []
        for e in inner_trace:
            lines.append(f"- {e.get('tool_name')}: {e.get('summary', '')[:500]}")
        return "\n".join(lines)

    def _generator_cfg(self, key: str, default: Any) -> Any:
        return (self.config or {}).get(key, default)

    def _implement_system_prompt(self, *, fix_round: bool) -> str:
        base = (
            "你是 Harness Generator Agent。根据 Evaluator 的 issues 修改 agent_rag 产品代码。\n"
            "【硬性要求】回复中必须包含至少一个 ```python 代码块，禁止只输出中文分析或 pytest 复述。\n\n"
            "【修改范围（重要）】\n"
            "- 只允许修改当前任务的 target_file（agent_rag 下的产品 .py），不要改测试文件或其它路径。\n"
            "- 主目标是 task 的 symbol，但若 pytest/issues 栈指向同文件其它方法（如 _get_encoder、"
            "_get_llm、_cosine_similarity），必须在同一 ```python 代码块内一并输出这些方法的完整 def。\n"
            "- 禁止以「只实现一个方法」为由拒绝修改依赖 helper；禁止以「需改多处」为由只写说明。\n"
            "- 一个代码块可含多个 def（先 helper，后主 symbol），均为 target_class 内类方法（4 空格缩进）。\n"
            "- 禁止输出 pytest 测试（def test_*）、禁止 if __name__ == '__main__'、"
            "禁止独立验证脚本；测试由 Evaluator 写入 test/ 目录。\n"
            "- 不要输出 unified diff。\n\n"
            "【跨项目 import 与 MODULAR 集成（tech_doc §0–§7）】\n"
            "- agent_rag 引用 MODULAR 父仓时必须使用顶层包名 src（LLMFactory、DenseEncoder、Message 等）。\n"
            "- 禁止改成 agent_rag.libs.* / agent_rag.ingestion.*。\n"
            "- 若 user prompt 含「=== … 实现参考 ===」段（encoder/llm/mcp/executor 等），"
            "须按参考结构输出完整 def，不要只改 import 或只写中文分析。\n"
            "- pytest 栈指向 _get_encoder、_get_llm、_evidence_* 等 helper 时，"
            "与主 symbol 在同一 ```python 块内一并输出。\n\n"
            "注意：上轮 Evaluator 问题（issues）可能包含：\n"
            "- pytest 失败输出（断言报错、import 错误、栈里其它 def 名）\n"
            "- Evaluator 对测试文件的操作记录\n"
            "- LLM 终判的分析结论\n\n"
            "若 issues 指出产品代码缺陷：直接输出修复后的完整方法实现，不要解释。\n"
        )
        if fix_round:
            base += (
                "【修复轮】测试已存在且合理时，必须输出可落盘的 Python 方法；"
                "若栈在 _get_encoder 等 helper，与主 symbol 一起输出完整 def。\n"
            )
        else:
            base += (
                "若测试断言与 done_criteria 明显矛盾，可在代码块前用一行说明，"
                "但代码块仍必须存在。\n"
            )
        return base

    def _implement_user_prompt(
        self,
        task: HarnessTask,
        *,
        issues: str,
        spec_excerpt: str,
        fix_round: bool,
    ) -> str:
        target = task.get("target_file", "")
        symbol = task.get("symbol", "")
        regression_note = ""
        if gate_allows_product_fix(task):
            globs = task.get("regression_test_globs") or []
            gate_test = task.get("test_file", "")
            regression_note = (
                f"【门禁任务】修改产品后 Evaluator 将运行: {gate_test}"
                f"{(' 与 ' + ', '.join(globs)) if globs else ''}。\n"
            )
        head = (
            f"子任务: {task.get('title')}\n"
            f"说明: {task.get('description')}\n"
            f"完成标准: {task.get('done_criteria')}\n"
            f"目标文件: {target}\n"
            f"主符号 symbol: {symbol}\n"
            f"{regression_note}"
            f"（可在同文件内同时修改 pytest 栈/traceback 涉及的其它 def，如 _get_encoder、_get_llm）\n"
            f"上轮 Evaluator 问题:\n{issues}\n\n"
            f"=== 当前任务规格（从 tech_doc 提取，优先参照此段）===\n"
            f"{spec_excerpt}\n\n"
        )
        hints_block = self._integration_hints_block(task=task, symbol=symbol, issues=issues)
        if fix_round:
            return head + hints_block + (
                "=== 修复轮：仅附上目标文件当前内容（勿依赖全文快照）===\n"
                f"{self._read_target_file_excerpt(target)}\n"
            )
        return head + hints_block + (
            "=== 以下为完整项目上下文（含 tech_doc 全文 + 代码快照）===\n"
            f"{self._get_project_context()}"
        )

    def _integration_hints_enabled(self) -> bool:
        return integration_hints_enabled({"generator": self.config or {}})

    def _integration_hints_block(
        self, *, task: HarnessTask, symbol: str, issues: str
    ) -> str:
        if not self._integration_hints_enabled():
            return ""
        target = str(task.get("target_file", ""))
        if not needs_integration_hints(symbol=symbol, issues=issues, target_file=target):
            return ""
        return collect_integration_hints(
            symbol=symbol,
            issues=issues,
            target_file=target,
            primary_symbol=symbol,
        )

    def _read_target_file_excerpt(self, target: str, max_chars: int = 40_000) -> str:
        rel = str(target or "").strip()
        if not rel:
            return "（无目标文件）"
        path = self.package_root / rel
        if not path.is_file():
            return f"（文件不存在: {rel}）"
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n... [truncated, total {len(text)} chars]"

    def _implement_step(self, task: HarnessTask, eval_result: HarnessEvalResult | None) -> str:
        if task.get("skip_implementation") and not gate_allows_product_fix(task):
            if is_gate_task(task):
                return (
                    "[gate] 本任务为测试门禁（pytest 验收），无需修改 agent_rag 产品实现。"
                    f" 目标测试: {task.get('test_file', '')}"
                )
            return (
                f"[stub] 待实现 {task.get('target_file', '')}::{task.get('symbol', '')}。"
                "（skip_implementation）"
            )

        symbol = task.get("symbol", "")
        target = task.get("target_file", "")
        issues = (eval_result or {}).get("issues", "")
        fix_round = bool(eval_result and not eval_result.get("passed"))

        if self._llm_bundle is not None:
            from harness.planner.parsing import extract_spec_excerpt

            task_id = str(task.get("id", ""))
            target_class = str(task.get("target_class") or task.get("module", ""))
            spec_excerpt = extract_spec_excerpt(
                self._get_project_context(),
                task_id,
                symbol,
                target_class=target_class,
            ) if task_id and symbol else ""

            system = self._implement_system_prompt(fix_round=fix_round)
            user = self._implement_user_prompt(
                task,
                issues=issues,
                spec_excerpt=spec_excerpt,
                fix_round=fix_round,
            )
            try:
                return chat(
                    self._llm_bundle,
                    system=system,
                    user=user,
                    harness_cfg=self.harness_cfg,
                    agent_key="generator",
                )
            except Exception as e:
                return f"[LLM error] {e}"

        return (
            f"[stub] 待实现 {target}::{symbol}。"
            f" 请在 config/harness.yaml 配置 llm 段并设置 llm_enabled: true。"
            f" 上轮 issues: {issues}"
        )

    def _write_draft_to_disk(self, task: HarnessTask, draft: str) -> WriteResult:
        """将 Generator 生成的代码写入 target_file。"""
        task_id = str(task.get("id", ""))
        if task.get("skip_implementation") and not gate_allows_product_fix(task):
            return WriteResult(False, "skip_gate")
        target = str(task.get("target_file", "")).strip()
        if not target:
            logger.warning("Generator 落盘跳过 task=%s reason=skip_no_target", task_id)
            return WriteResult(False, "skip_no_target")
        if not draft or draft.startswith(("[stub]", "[gate]", "[error]", "[LLM error]")):
            reason = "skip_llm_error" if str(draft).startswith("[LLM error]") else "skip_bad_draft"
            logger.warning(
                "Generator 落盘跳过 task=%s reason=%s draft_prefix=%s",
                task_id,
                reason,
                str(draft)[:120],
            )
            return WriteResult(False, reason)

        path = self.package_root / target
        path.parent.mkdir(parents=True, exist_ok=True)

        relaxed = bool(self._generator_cfg("relaxed_code_extraction", True))
        log_skip = int(self._generator_cfg("log_draft_on_skip_chars", 400))
        code = extract_code_from_draft(draft, relaxed=relaxed)
        if not code.strip():
            logger.warning(
                "Generator 落盘跳过 task=%s reason=skip_no_code draft_prefix=%s",
                task_id,
                str(draft)[:log_skip],
            )
            return WriteResult(False, "skip_no_code")

        symbol = str(task.get("symbol", "")).strip()
        target_class = str(task.get("target_class") or task.get("module") or "").strip()
        merge_helpers = bool(self._generator_cfg("merge_helpers_from_draft", True))
        gate_fix = gate_allows_product_fix(task)
        if (
            symbol
            and symbol == "gate"
            and gate_fix
            and list_def_symbols(code)
        ):
            symbol = ""
        if symbol and draft_looks_like_test_script(code, symbol, target_class=target_class):
            logger.warning(
                "Generator 落盘跳过 task=%s reason=skip_test_draft code_prefix=%s",
                task_id,
                code[:120],
            )
            return WriteResult(False, "skip_test_draft")
        if (
            symbol
            and not code_covers_symbol(code, symbol, target_class=target_class)
            and not gate_fix
            and not draft_has_mergeable_product_defs(code)
        ):
            logger.warning(
                "Generator 落盘跳过 task=%s reason=skip_no_symbol code_prefix=%s",
                task_id,
                code[:120],
            )
            return WriteResult(False, "skip_no_symbol")

        if path.is_file():
            existing = path.read_text(encoding="utf-8", errors="replace")
            merged = self._merge_into_existing(existing, code, task)
            if symbol and merged == existing and draft_has_mergeable_product_defs(code):
                logger.warning(
                    "Generator 落盘跳过 task=%s reason=skip_merge_unchanged symbol=%s",
                    task_id,
                    symbol,
                )
                return WriteResult(False, "skip_merge_unchanged")
        else:
            merged = code

        guard_reason = self._merge_guard_reason(merged, task, code=code)
        if guard_reason:
            logger.warning(
                "Generator 落盘跳过 task=%s reason=%s class=%s symbol=%s",
                task_id,
                guard_reason,
                target_class,
                symbol,
            )
            return WriteResult(False, guard_reason)

        write_result = self._validate_and_write(path, merged, task_id, target, symbol)
        if write_result.ok:
            return write_result

        if write_result.reason != "skip_merged_syntax":
            return write_result

        if not bool(self._generator_cfg("allow_partial_merge", True)):
            return write_result

        partial = self._try_partial_method_merge(
            path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "",
            code,
            task,
        )
        if partial is not None:
            return self._validate_and_write(
                path, partial, task_id, target, symbol, reason="wrote_partial_merge"
            )
        return write_result

    def _validate_and_write(
        self,
        path: Path,
        merged: str,
        task_id: str,
        target: str,
        symbol: str,
        *,
        reason: str = "wrote_merged",
    ) -> WriteResult:
        try:
            ast.parse(merged)
        except SyntaxError as exc:
            logger.warning(
                "Generator 落盘跳过 task=%s reason=skip_merged_syntax error=%s",
                task_id,
                exc,
            )
            return WriteResult(False, "skip_merged_syntax")

        path.write_text(merged, encoding="utf-8")
        logger.info(
            "Generator 落盘成功 task=%s path=%s symbol=%s reason=%s",
            task_id,
            target,
            symbol,
            reason,
        )
        return WriteResult(True, reason)

    def _merge_guard_reason(
        self,
        merged: str,
        task: HarnessTask,
        *,
        code: str = "",
    ) -> str | None:
        """Return skip reason when merged output fails product merge guards."""
        target_class = str(task.get("target_class") or task.get("module") or "").strip()
        symbol = str(task.get("symbol", "")).strip()
        if target_class and not merged_preserves_target_class(merged, target_class):
            return "skip_lost_target_class"
        draft = code or merged
        if (
            symbol
            and target_class
            and code_covers_symbol(draft, symbol, target_class=target_class)
            and not method_in_target_class(merged, target_class, symbol)
        ):
            return "skip_symbol_not_in_class"
        return None

    def _try_partial_method_merge(
        self,
        existing: str,
        code: str,
        task: HarnessTask,
    ) -> str | None:
        """If full merge fails syntax check, merge methods one-by-one."""
        if not existing.strip():
            return None
        symbol = str(task.get("symbol", "")).strip()
        target_class = str(task.get("target_class") or task.get("module") or "").strip()
        symbols = prioritize_symbols(list_product_def_symbols(code), symbol)
        if not symbols:
            return None
        result = existing
        merged_any = False
        primary_merged = False
        needs_primary = bool(
            symbol and code_covers_symbol(code, symbol, target_class=target_class)
        )
        for sym in symbols:
            if sym.startswith("test_"):
                continue
            candidate = merge_method_into_class(
                result,
                code,
                symbol=sym,
                target_class=target_class,
            )
            if candidate is None:
                continue
            try:
                ast.parse(candidate)
            except SyntaxError:
                continue
            if self._merge_guard_reason(candidate, task, code=code):
                continue
            result = candidate
            merged_any = True
            if sym == symbol:
                primary_merged = True
        if not merged_any:
            return None
        if needs_primary and not primary_merged:
            logger.warning(
                "Generator partial merge 拒绝 task=%s reason=skip_partial_no_primary symbol=%s",
                task.get("id"),
                symbol,
            )
            return None
        return result

    def _extract_code_from_draft(self, draft: str) -> str:
        """Backward-compatible wrapper."""
        relaxed = bool(self._generator_cfg("relaxed_code_extraction", True))
        return extract_code_from_draft(draft, relaxed=relaxed)

    def _merge_into_existing(self, existing: str, new_code: str, task: HarnessTask) -> str:
        """将新生成的方法合并进 target_class，并清理类外的同名模块级 def。"""
        symbol = str(task.get("symbol", "")).strip()
        target_class = str(task.get("target_class") or task.get("module") or "").strip()
        merge_into_class = self.config.get("merge_into_class", True)
        merge_helpers = bool(self._generator_cfg("merge_helpers_from_draft", True))

        if gate_allows_product_fix(task):
            symbols = list_product_def_symbols(new_code)
            if symbols and merge_into_class:
                return merge_all_methods_from_draft(
                    existing,
                    new_code,
                    symbols=prioritize_symbols(symbols, symbol if symbol != "gate" else ""),
                    target_class=target_class,
                )

        if merge_into_class and symbol and merge_helpers:
            symbols = prioritize_symbols(list_product_def_symbols(new_code), symbol)
            if len(symbols) > 1 or (symbols and symbols[0] != symbol):
                return merge_all_methods_from_draft(
                    existing,
                    new_code,
                    symbols=symbols,
                    target_class=target_class,
                )

        if merge_into_class and symbol and draft_has_mergeable_product_defs(new_code):
            merged = merge_all_methods_from_draft(
                existing,
                new_code,
                symbols=prioritize_symbols(list_product_def_symbols(new_code), symbol),
                target_class=target_class,
            )
            if merged != existing:
                return merged

        if merge_into_class and symbol:
            merged = merge_method_into_class(
                existing,
                new_code,
                symbol=symbol,
                target_class=target_class,
            )
            if merged is not None:
                return merged
            return existing
        if not existing.strip():
            return new_code
        return existing

    def node_implement(self, state: dict) -> dict:
        if state.get("terminal"):
            return {}
        task = state["task"]
        step = int(state.get("step_count", 0)) + 1
        last_eval = state.get("last_eval")

        # 如果任务没有 target_file，Generator 无法写代码，直接标记终止
        target = str(task.get("target_file", "")).strip()
        if not target and not is_gate_task(task) and not task.get("skip_implementation"):
            logger.warning("Generator 终止 task=%s reason=no_target_file", task.get("id"))
            result = HarnessSubtaskResult(
                task_id=str(task.get("id", "unknown")),
                status="needs_replan",
                draft_text="",
                tool_trace=list(state.get("inner_trace") or []),
                observation_for_replan=(
                    f"子任务: id={task.get('id')} symbol={task.get('symbol')} "
                    f"target_file={task.get('target_file')} test_file={task.get('test_file')}\n"
                    "任务缺少 target_file，Generator 无法写入代码。需要 Planner 指定目标文件。"
                ),
                artifacts={},
            )
            return {"subtask_result": result, "terminal": True}

        draft = self._implement_step(task, last_eval)
        write_result = self._write_draft_to_disk(task, draft)
        trace = list(state.get("inner_trace") or [])
        draft_ok = not str(draft).startswith(("[error]", "[LLM error]"))
        trace.append(
            {
                "tool_name": "implement",
                "ok": draft_ok and write_result.ok,
                "write_ok": write_result.ok,
                "write_reason": write_result.reason,
                "summary": draft[:800],
            }
        )
        return {
            "step_count": step,
            "draft_text": draft,
            "inner_trace": trace,
        }

    def node_evaluate(self, state: dict) -> dict:
        """LangGraph 节点：调用 Evaluator 检查代码，根据结果决定继续循环还是终止。

        终止条件（优先级从高到低）：
        1. passed=True → success（代码通过了）
        2. status="needs_replan" → 当前方案走不通，交给 Planner 重新规划
        3. 门禁任务失败 → 门禁不循环，直接返回 failed
        4. step >= max_inner_steps → 超次数，放弃
        5. 以上都不满足 → 继续循环（回到 node_implement 改代码）
        """
        if state.get("terminal"):
            return {}

        task = state["task"]
        evaluator = self._evaluator
        if evaluator is None:
            raise RuntimeError("Generator 未绑定 Evaluator，请先 set_evaluator()")

        draft = state.get("draft_text", "")
        # 把 inner_trace 格式化成文本摘要，供 Evaluator 的 quick_rule_check 检查连续错误
        summary = self._format_trace(state.get("inner_trace") or [])

        # --- 调用 Evaluator ---
        # 先快速预检：连续 [error] 达阈值？是则直接 hard_fail
        rule = evaluator.quick_rule_check(task, summary)
        # 预检没问题则走完整评估（assess_tests → pytest → llm_evaluate 整个流水线）
        last_eval = rule if rule is not None else evaluator.evaluate(task, summary, draft)

        task_id = str(task.get("id", "unknown"))
        step = int(state.get("step_count", 0))

        # --- 终止条件 1：LLM 终判认为方案走不通 ---
        if last_eval.get("status") == "needs_replan":
            result = HarnessSubtaskResult(
                task_id=task_id,
                status="needs_replan",
                draft_text=draft,
                tool_trace=list(state.get("inner_trace") or []),
                # observation 传给 Planner，让它知道为什么走不通
                observation_for_replan=evaluator.to_planner_observation(
                    last_eval, task=task, step_count=step
                ),
                artifacts={"last_draft": draft},
            )
            return {"last_eval": last_eval, "subtask_result": result, "terminal": True}

        # --- 终止条件 2：代码通过了 ---
        if last_eval.get("passed") and not last_eval.get("require_more_tools"):
            result = HarnessSubtaskResult(
                task_id=task_id,
                status="success",
                draft_text=draft,
                tool_trace=list(state.get("inner_trace") or []),
                observation_for_replan="",  # 成功了不需要 replan
                artifacts={"last_draft": draft},
            )
            return {"last_eval": last_eval, "subtask_result": result, "terminal": True}

        # --- 终止条件 3：仅验收测试的门禁失败（不循环 implement）---
        if is_gate_task(task) and not gate_allows_product_fix(task):
            obs = evaluator.to_planner_observation(last_eval, task=task, step_count=step)
            result = HarnessSubtaskResult(
                task_id=task_id,
                status="failed",
                draft_text=draft,
                tool_trace=list(state.get("inner_trace") or []),
                observation_for_replan=obs,
                artifacts={"last_draft": draft, "gate": True},
            )
            return {"last_eval": last_eval, "subtask_result": result, "terminal": True}

        # --- 终止条件 4：达到最大循环次数，放弃 ---
        if step >= self.max_inner_steps:
            exhausted = HarnessEvalResult(
                passed=False,
                score=0.0,
                require_more_tools=False,
                status="ok",
                issues="max_inner_steps",
            )
            # 记录到 TEST_PROGRESS.md：标记 ❌
            if hasattr(evaluator, "record_progress"):
                evaluator.record_progress(
                    task,
                    summary,
                    exhausted,
                    progress_icon="❌",
                    progress_note=(
                        f"已达 generator.max_inner_steps={self.max_inner_steps}"
                    ),
                )
            obs = evaluator.to_planner_observation(
                last_eval or exhausted, task=task, step_count=step
            )
            result = HarnessSubtaskResult(
                task_id=task_id,
                status="failed",
                draft_text=draft,
                tool_trace=list(state.get("inner_trace") or []),
                observation_for_replan=obs,
                artifacts={"last_draft": draft},
            )
            return {"last_eval": last_eval, "subtask_result": result, "terminal": True}

        # --- 以上都不满足：继续循环 ---
        if not (state.get("inner_trace") or [])[-1].get("write_ok") if state.get("inner_trace") else False:
            last_eval = dict(last_eval or {})
            write_reason = (state.get("inner_trace") or [])[-1].get("write_reason", "")
            if write_reason == "skip_test_draft":
                skip_hint = (
                    "上轮 draft 像 pytest/验证脚本（test_*、__main__、Mock 等），"
                    f"不能写入产品文件 {task.get('target_file')}。"
                    "必须输出 target_class 内的 ```python 类方法 def "
                    f"{task.get('symbol')}（可含 helper def），禁止测试脚本。"
                )
            elif write_reason == "skip_lost_target_class":
                skip_hint = (
                    "上轮 merge 会丢失目标类定义。"
                    "禁止整文件替换；只输出类内方法 def，不要输出独立脚本。"
                )
            elif write_reason == "skip_symbol_not_in_class":
                skip_hint = (
                    f"上轮 merge 未把 {task.get('symbol')} 写入 {task.get('target_class')} 类内。"
                    "只输出该类内的 ```python def ...```，不要写到类外或模块级。"
                )
            else:
                skip_hint = (
                    "上轮 Generator 未能落盘（write_ok=False）。"
                    "必须输出 ```python 代码块，包含修复后的类方法；"
                    "可在一个块内写多个 def（含依赖 helper）。"
                )
            issues = str(last_eval.get("issues", ""))
            last_eval["issues"] = f"{skip_hint}\n\n{issues}".strip()
        return {"last_eval": last_eval}
