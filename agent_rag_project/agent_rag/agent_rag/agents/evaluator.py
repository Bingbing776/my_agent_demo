"""
§5 Evaluator — 子任务内评估（MCP 摘要 + 草稿）。

规格：docs/tech_doc.md §5。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_EVAL_SYSTEM_PROMPT = """你是 RAG 子任务评估器。只输出一个合法 JSON 对象，无 markdown 围栏、无前后说明。
键仅：passed (bool)、score (0~1 float)、require_more_tools (bool)、status ("ok"|"needs_replan"|"hard_fail")、issues (str)。
评估范围：只判断当前子任务在 tool_trace_summary + draft_answer 下是否达标；global_query 仅作背景。
passed=True 条件：done_criteria/description 基本达成，有一定证据支持即可，不要求完美；
若 intent 为检索类但工具调用失败或返回空，才设 passed=False。
require_more_tools=True 表示缺乏核心证据且再调工具很有可能补齐；如果已有基本证据能回答问题，设为 False。
倾向于宽松评估：有部分相关证据即可通过，避免无限循环。
status 优先级：hard_fail > needs_replan > ok。hard_fail 或 needs_replan 时 passed 必须为 False。
issues 为简短中文说明，≤200 字。"""


class Evaluator:
    """子任务内评估：quick_rule_check、evaluate、to_planner_observation。"""

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._eval_max_chars = int(self._config.get("eval_max_chars", 4000))
        self._strict_json = bool(self._config.get("strict_json", True))
        prompt = self._config.get("eval_system_prompt")
        self._eval_system_prompt = (
            prompt if isinstance(prompt, str) and prompt.strip() else _DEFAULT_EVAL_SYSTEM_PROMPT
        )
        self._llm: Any = None

    def _get_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        try:
            from src.core.settings import load_settings
            from src.libs.llm.llm_factory import LLMFactory

            llm_cfg = self._config.get("llm", {})
            if llm_cfg:
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            else:
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            self._llm = LLMFactory.create(settings)
        except Exception as e:
            print(f"[DEBUG Evaluator._get_llm] FAILED, using stub: {e}", flush=True)
            from src.libs.llm.base_llm import ChatResponse

            class _StubLLM:
                def chat(self, messages, **kwargs):
                    return ChatResponse(
                        content=json.dumps(
                            {
                                "passed": False,
                                "score": 0.0,
                                "require_more_tools": True,
                                "status": "ok",
                                "issues": "stub evaluation",
                            }
                        ),
                        model="stub",
                    )

            self._llm = _StubLLM()
        return self._llm

    def _resolve_error_streak_threshold(self) -> int:
        rag_agent = self._config.get("rag_agent", {})
        if isinstance(rag_agent, dict):
            evaluator_cfg = rag_agent.get("evaluator", {})
            if isinstance(evaluator_cfg, dict):
                val = evaluator_cfg.get("quick_rule_error_streak")
                if val is not None:
                    try:
                        return max(1, int(val))
                    except (TypeError, ValueError):
                        return 3

        val = self._config.get("quick_rule_error_streak")
        if val is not None:
            try:
                return max(1, int(val))
            except (TypeError, ValueError):
                return 3
        return 3

    def _has_consecutive_error_streak(self, tool_trace_summary: str, n: int) -> bool:
        if not tool_trace_summary or n <= 0:
            return False

        lines = [line for line in tool_trace_summary.splitlines() if line.strip()]
        if len(lines) < n:
            return False

        consecutive = 0
        for line in lines:
            if "[error]" in line.lower():
                consecutive += 1
                if consecutive >= n:
                    return True
            else:
                consecutive = 0
        return False

    def quick_rule_check(
        self,
        task: dict,
        tool_trace_summary: str | None,
    ) -> Optional[dict]:
        """纯规则预检；命中硬规则返回 EvalResult，否则 None。"""
        _ = task
        n = self._resolve_error_streak_threshold()
        summary = tool_trace_summary or ""
        if summary and self._has_consecutive_error_streak(summary, n):
            return {
                "passed": False,
                "score": 0.0,
                "require_more_tools": False,
                "status": "hard_fail",
                "issues": (
                    f"连续 {n} 次 MCP/填参失败"
                    f"（工具执行摘要中检测到连续 [error] 标记）。"
                ),
            }
        return None

    def evaluate(
        self,
        global_query: str,
        task: dict,
        tool_trace_summary: str,
        draft_answer: str,
    ) -> dict:
        """LLM 评估当前子任务，返回 EvalResult。"""
        from src.libs.llm.base_llm import Message

        user_prompt = self._build_user_prompt(
            global_query,
            task,
            tool_trace_summary or "",
            draft_answer or "",
        )
        messages = [
            Message(role="system", content=self._eval_system_prompt),
            Message(role="user", content=user_prompt),
        ]
        try:
            response = self._get_llm().chat(messages)
            content = getattr(response, "content", "") or ""
        except Exception as exc:
            logger.warning("Evaluator.evaluate LLM call failed: %s", exc)
            return self._failed_eval_result("LLM evaluation failed")

        result = self._parse_eval_response(content)
        result = self._apply_post_rules(result, task, tool_trace_summary or "")
        return self._enforce_consistency(result)

    def to_planner_observation(
        self,
        eval_result: dict,
        max_chars: int | None = None,
    ) -> str:
        """将 EvalResult 压成 Planner replan 可用的短 observation。"""
        if not isinstance(eval_result, dict):
            return ""

        cap = max_chars if max_chars is not None else self._eval_max_chars
        status = str(eval_result.get("status", "ok"))
        issues = eval_result.get("issues", "")
        if isinstance(issues, list):
            issues = "; ".join(str(x) for x in issues if x)
        else:
            issues = str(issues) if issues else ""

        require_more = eval_result.get("require_more_tools", False)
        passed = eval_result.get("passed", False)
        score = eval_result.get("score", 0.0)

        parts = [f"status={status}"]
        if not passed:
            parts.append("passed=False")
        parts.append(f"score={float(score):.2f}")
        if require_more:
            parts.append("require_more_tools=True")
        if issues:
            parts.append(f"issues: {issues}")

        observation = "; ".join(parts)
        if cap and len(observation) > cap:
            observation = observation[: cap - 13] + "…[truncated]"
        return observation

    def _build_user_prompt(
        self,
        global_query: str,
        task: dict,
        tool_trace_summary: str,
        draft_answer: str,
    ) -> str:
        task = task or {}
        sections = [
            f"全局用户问题\n{global_query.strip() if global_query else '（无）'}",
            (
                "当前子任务\n"
                f"id: {task.get('id', '（无）')}\n"
                f"description: {task.get('description', '')}\n"
                f"intent: {task.get('intent', '')}\n"
                f"suggested_tool: {task.get('suggested_tool', '（无）')}\n"
                f"done_criteria: {self._format_task_field(task.get('done_criteria'))}\n"
                f"replan_triggers: {self._format_task_field(task.get('replan_triggers'))}"
            ),
            f"工具执行摘要\n{tool_trace_summary.strip() if tool_trace_summary.strip() else '（无）'}",
            f"当前草稿\n{draft_answer.strip() if draft_answer.strip() else '（无）'}",
        ]
        text = "\n\n".join(sections)
        cap = self._eval_max_chars
        if cap and len(text) > cap:
            text = text[: cap - 13] + "…[truncated]"
        return text

    @staticmethod
    def _format_task_field(value: Any) -> str:
        if value is None:
            return "（无）"
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value) if value else "（无）"
        text = str(value).strip()
        return text if text else "（无）"

    def _parse_eval_response(self, content: str) -> dict:
        text = self._strip_markdown_fence(content.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            if self._strict_json:
                return self._failed_eval_result("invalid JSON from evaluator LLM")
            return self._default_eval_result()

        if not isinstance(data, dict):
            if self._strict_json:
                return self._failed_eval_result("evaluator LLM did not return a JSON object")
            return self._default_eval_result()

        return self._normalize_eval_result(data)

    @staticmethod
    def _strip_markdown_fence(text: str) -> str:
        fence = re.match(r"^```(?:json)?\s*\n([\s\S]*?)\n```\s*$", text, re.IGNORECASE)
        if fence:
            return fence.group(1).strip()
        return text

    @staticmethod
    def _default_eval_result() -> dict:
        return {
            "passed": False,
            "score": 0.0,
            "require_more_tools": True,
            "status": "ok",
            "issues": "",
        }

    def _failed_eval_result(self, issue: str) -> dict:
        return {
            "passed": False,
            "score": 0.0,
            "require_more_tools": True,
            "status": "ok",
            "issues": issue,
        }

    def _normalize_eval_result(self, data: dict) -> dict:
        result = self._default_eval_result()
        if "passed" in data:
            result["passed"] = bool(data["passed"])
        if "score" in data:
            try:
                score = float(data["score"])
                result["score"] = max(0.0, min(1.0, score))
            except (TypeError, ValueError):
                pass
        if "require_more_tools" in data:
            result["require_more_tools"] = bool(data["require_more_tools"])
        if "status" in data and data["status"] in ("ok", "needs_replan", "hard_fail"):
            result["status"] = data["status"]
        if "issues" in data:
            issues = data["issues"]
            if isinstance(issues, list):
                result["issues"] = "; ".join(str(x) for x in issues if x)
            else:
                result["issues"] = str(issues) if issues is not None else ""
        return result

    def _apply_post_rules(self, result: dict, task: dict, tool_trace_summary: str) -> dict:
        intent = str((task or {}).get("intent", "")).lower()
        trace_empty = not (tool_trace_summary or "").strip()
        if trace_empty and "retriev" in intent:
            result["passed"] = False
            result["require_more_tools"] = True
            if not result.get("issues"):
                result["issues"] = "无工具执行摘要，检索类子任务证据不足"
        return result

    def _enforce_consistency(self, result: dict) -> dict:
        status = result.get("status", "ok")
        if status in ("hard_fail", "needs_replan"):
            result["passed"] = False
        if status == "needs_replan":
            result["require_more_tools"] = False
        if result.get("passed") and result.get("require_more_tools"):
            result["require_more_tools"] = False
        if status == "hard_fail" and float(result.get("score", 0)) > 0.2:
            result["score"] = 0.2
        issues = result.get("issues", "")
        if isinstance(issues, str) and len(issues) > 200:
            result["issues"] = issues[:197] + "..."
        return result
