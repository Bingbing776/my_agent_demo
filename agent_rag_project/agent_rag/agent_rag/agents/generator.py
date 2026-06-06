"""
§6 Generator — 子任务内 MCP 循环 + Evaluator。

规格：docs/tech_doc.md §6。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class Generator:
    """子任务内：MCP 调用、草稿生成、评估循环。"""

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._inner_trace: list[dict[str, Any]] = []
        self._inner_images: list[dict[str, Any]] = []
        self._subtask_step_count = 0
        self._llm: Any = None

    def _get_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        try:
            from src.core.settings import load_settings
            from src.libs.llm.llm_factory import LLMFactory

            llm_cfg = self._config.get("llm", {})
            from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            self._llm = LLMFactory.create(settings)
        except Exception as e:
            print(f"[DEBUG Generator._get_llm] FAILED, using stub: {e}", flush=True)
            from src.libs.llm.base_llm import ChatResponse

            class _StubLLM:
                def chat(self, messages, **kwargs):
                    return ChatResponse(
                        content=json.dumps(
                            {"action": "stop", "tool_name": "", "reason": "stub"}
                        ),
                        model="stub",
                    )

            self._llm = _StubLLM()
        return self._llm

    def reset_subtask_state(self) -> None:
        self._inner_trace = []
        self._inner_images = []
        self._subtask_step_count = 0

    def _collect_images_from_raw(
        self,
        raw: dict,
        tool_name: str = "",
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, dict):
            return []
        max_images = int(self._config.get("max_images_per_subtask", 0) or 0)
        out: list[dict[str, Any]] = []

        images_key = raw.get("images")
        if isinstance(images_key, list):
            for item in images_key:
                if isinstance(item, dict) and item.get("data"):
                    out.append(dict(item))

        for block in raw.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "image":
                continue
            data = block.get("data") or ""
            if not str(data).strip():
                continue
            mime = block.get("mimeType") or block.get("mime_type") or "image/png"
            entry: dict[str, Any] = {
                "tool_name": tool_name,
                "mime_type": mime,
                "data": data,
            }
            source = block.get("source")
            if source:
                entry["source"] = source
            out.append(entry)
            if max_images > 0 and len(out) >= max_images:
                break
        return out

    def summarize_mcp_result(self, raw: dict, max_chars: int | None = None) -> str:
        if not isinstance(raw, dict):
            return ""
        cap = max_chars
        if cap is None:
            # 从 generator 子配置或顶层读取
            gen_cfg = self._config.get("generator", {}) if isinstance(self._config.get("generator"), dict) else {}
            cap = int(gen_cfg.get("mcp_summary_max_chars", 0) or self._config.get("mcp_summary_max_chars", 0))
            # 0 表示不截断

        parts: list[str] = []
        if raw.get("isError"):
            parts.append("[error]")
        image_count = 0
        for block in raw.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("text") or "")
                if text:
                    parts.append(text)
            elif block.get("type") == "image":
                image_count += 1
        if image_count:
            parts.append(f"[含 {image_count} 张图，未展开]")
        summary = " ".join(parts).strip()
        if cap and len(summary) > cap:
            summary = summary[: cap - 13] + "…[truncated]"
        return summary

    def _format_trace(self, tool_trace: list) -> str:
        if not tool_trace:
            return "（尚无）"
        cap = int(self._config.get("inner_trace_max_chars", 4000))
        lines: list[str] = []
        for entry in tool_trace:
            if not isinstance(entry, dict):
                continue
            name = entry.get("tool_name", "")
            summary = str(entry.get("summary", ""))
            lines.append(f"{name}: {summary}")
        text = "\n".join(lines)
        if cap and len(text) > cap:
            text = text[: cap - 13] + "…[truncated]"
        return text

    def _evidence_text_for_subtask(self, task: dict) -> str:
        """子任务评估/草稿用的证据文本：优先本任务 tool_trace，否则用 prior_observation。"""
        if self._inner_trace:
            return self._format_trace(self._inner_trace)
        prior = str(task.get("prior_observation") or "").strip()
        if prior:
            cap = int(self._config.get("inner_trace_max_chars", 4000))
            if cap and len(prior) > cap:
                return prior[: cap - 13] + "…[truncated]"
            return prior
        return self._format_trace(self._inner_trace)

    async def draft_partial_answer(
        self,
        global_query: str,
        task: dict,
        tool_trace_text: str,
    ) -> str:
        from src.libs.llm.base_llm import Message

        system = self._config.get(
            "draft_system_prompt",
            "你是 RAG 子任务草稿撰写器。只输出纯文本草稿，不要 JSON 或 markdown 围栏。",
        )
        user = (
            f"全局用户问题\n{global_query or '（无）'}\n\n"
            f"当前子任务\n{task.get('description', '')}\n"
            f"intent: {task.get('intent', '')}\n\n"
            f"工具执行摘要\n{tool_trace_text or '（尚无工具结果）'}"
        )
        cap = int(self._config.get("draft_max_chars", 1500))
        try:
            response = self._get_llm().chat(
                [Message(role="system", content=system), Message(role="user", content=user)]
            )
            text = (getattr(response, "content", "") or "").strip()
            if text:
                if cap and len(text) > cap:
                    return text[: cap - 13] + "…[truncated]"
                return text
        except Exception as exc:
            logger.warning("draft_partial_answer LLM failed: %s", exc)
        fallback = (tool_trace_text or "")[:cap] if cap else (tool_trace_text or "")
        return fallback or "[draft_failed]"

    async def choose_next_action(
        self,
        global_query: str,
        task: dict,
        tool_trace: list,
        last_eval: dict | None = None,
        tool_names: list | None = None,
    ) -> dict:
        max_steps = int(self._config.get("max_inner_steps", 8))
        if self._subtask_step_count >= max_steps:
            return {"action": "stop", "tool_name": "", "reason": "max_inner_steps reached"}

        if last_eval:
            if last_eval.get("status") == "needs_replan":
                return {
                    "action": "replan",
                    "tool_name": "",
                    "reason": str(last_eval.get("issues", "needs_replan")),
                }
            if last_eval.get("passed") and not last_eval.get("require_more_tools"):
                return {"action": "stop", "tool_name": "", "reason": "evaluation passed"}

        cold_start = bool(self._config.get("cold_start_use_suggested_tool", True))
        suggested = str(task.get("suggested_tool") or "").strip()
        names = list(tool_names or [])
        if not names and suggested:
            names = [suggested]
        intent = str(task.get("intent") or "").lower()
        prior = str(task.get("prior_observation") or "").strip()
        if not tool_trace and not suggested and prior:
            if intent in ("answer", "synthesize", "summarize", "compile", "write", "explain", "draft"):
                return {
                    "action": "stop",
                    "tool_name": "",
                    "reason": "synthesis subtask; use prior_observation",
                }
        if cold_start and not tool_trace and suggested and suggested in names:
            return {
                "action": "call_tool",
                "tool_name": suggested,
                "reason": "planner suggested",
            }

        from src.libs.llm.base_llm import Message

        system = self._config.get(
            "choose_action_system_prompt",
            "你是子任务 MCP 工具调度器。只输出 JSON：action, tool_name, reason。",
        )
        eval_text = "（尚未评估）"
        if last_eval:
            eval_text = (
                f"passed={last_eval.get('passed')}; score={last_eval.get('score')}; "
                f"require_more_tools={last_eval.get('require_more_tools')}; "
                f"status={last_eval.get('status')}; issues={last_eval.get('issues')}"
            )
        user = (
            f"全局用户问题\n{global_query or ''}\n\n"
            f"当前子任务\n{task.get('description', '')}\n"
            f"suggested_tool: {suggested or '（无）'}\n\n"
            f"已执行步数: {len(tool_trace or [])} / {max_steps}\n\n"
            f"工具执行轨迹\n{self._format_trace(tool_trace or [])}\n\n"
            f"最近一次评估\n{eval_text}\n\n"
            f"可用工具名\n{', '.join(names) if names else suggested or '（无）'}"
        )
        try:
            response = self._get_llm().chat(
                [Message(role="system", content=system), Message(role="user", content=user)]
            )
            parsed = self._parse_next_action(getattr(response, "content", "") or "")
            if parsed:
                action = parsed.get("action", "stop")
                tool_name = str(parsed.get("tool_name") or "")
                if action == "call_tool" and tool_name and names and tool_name not in names:
                    return {"action": "replan", "tool_name": "", "reason": "invalid tool_name"}
                return {
                    "action": action,
                    "tool_name": tool_name if action == "call_tool" else "",
                    "reason": str(parsed.get("reason") or ""),
                }
        except Exception as exc:
            logger.warning("choose_next_action LLM failed: %s", exc)
        return {"action": "stop", "tool_name": "", "reason": "choose_action_failed"}

    def _parse_next_action(self, content: str) -> dict | None:
        text = content.strip()
        fence = re.match(r"^```(?:json)?\s*\n([\s\S]*?)\n```\s*$", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("action") in ("call_tool", "stop", "replan"):
                return data
        except json.JSONDecodeError:
            pass
        return None

    async def run_subtask(
        self,
        global_query: str,
        task: dict,
        executor: Any,
        get_input_schema: Callable[[str], dict],
        evaluator: Any,
        tool_names: list | None = None,
    ) -> dict:
        self.reset_subtask_state()
        task_id = str(task.get("id") or task.get("task_id") or "unknown")
        draft = ""
        last_eval: dict | None = None
        max_steps = int(self._config.get("max_inner_steps", 8))

        while self._subtask_step_count < max_steps:
            action = await self.choose_next_action(
                global_query,
                task,
                list(self._inner_trace),
                last_eval=last_eval,
                tool_names=tool_names,
            )
            if action.get("action") == "replan":
                obs = ""
                if last_eval:
                    obs = evaluator.to_planner_observation(last_eval)
                return self._subtask_result(
                    task_id,
                    "needs_replan",
                    draft,
                    obs or action.get("reason", ""),
                )
            if action.get("action") == "call_tool":
                tool_name = str(
                    action.get("tool_name") or task.get("suggested_tool") or ""
                ).strip()
                if not tool_name:
                    logger.warning(
                        "call_tool requested but no tool_name/suggested_tool on task %s",
                        task_id,
                    )
                else:
                    task["tool_name"] = tool_name
                    # 保留之前子任务传入的 prior_observation，追加当前子任务的 trace
                    existing_obs = task.get("prior_observation") or ""
                    current_trace = self._format_trace(self._inner_trace) if self._inner_trace else ""
                    if existing_obs and current_trace and current_trace != "（尚无）":
                        task["prior_observation"] = existing_obs + "\n" + current_trace
                    elif current_trace and current_trace != "（尚无）":
                        task["prior_observation"] = current_trace
                    # 如果 existing_obs 有值且 current_trace 为空，保持 existing_obs 不变
                    print(
                        f"[DEBUG Gen] call_tool={tool_name}, prior_obs length="
                        f"{len(task.get('prior_observation', ''))}, "
                        f"has_chunk_id={'chunk_id' in task.get('prior_observation', '')}",
                        flush=True,
                    )
                    raw = await executor.execute_task(task, get_input_schema)
                    summary = self.summarize_mcp_result(raw)
                    imgs = self._collect_images_from_raw(raw, tool_name)
                    self._inner_images.extend(imgs)
                    self._inner_trace.append(
                        {
                            "tool_name": tool_name,
                            "ok": not bool(raw.get("isError", False))
                            if isinstance(raw, dict)
                            else False,
                            "summary": summary,
                            "image_count": len(imgs),
                        }
                    )
                    self._subtask_step_count += 1

            trace_text = self._evidence_text_for_subtask(task)
            rule_hit = evaluator.quick_rule_check(task, trace_text)
            if rule_hit is not None:
                last_eval = rule_hit
            else:
                draft = await self.draft_partial_answer(global_query, task, trace_text)
                last_eval = evaluator.evaluate(global_query, task, trace_text, draft)

            if last_eval.get("status") == "needs_replan":
                return self._subtask_result(
                    task_id,
                    "needs_replan",
                    draft,
                    evaluator.to_planner_observation(last_eval),
                )
            if last_eval.get("passed") and not last_eval.get("require_more_tools"):
                return self._subtask_result(task_id, "success", draft, "")

            if action.get("action") == "stop":
                break

        status = "success" if last_eval and last_eval.get("passed") else "failed"
        obs = evaluator.to_planner_observation(last_eval) if last_eval else ""
        return self._subtask_result(task_id, status, draft, obs)

    def _subtask_result(
        self,
        task_id: str,
        status: str,
        draft_text: str,
        observation_for_replan: str,
    ) -> dict:
        return {
            "task_id": task_id,
            "status": status,
            "draft_text": draft_text or "",
            "tool_trace": list(self._inner_trace),
            "observation_for_replan": observation_for_replan or "",
            "citations": [],
            "images": list(self._inner_images),
        }
