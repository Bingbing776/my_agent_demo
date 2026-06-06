"""
§3.2 Executor — MCP 填参 + tools/call。

规格：docs/tech_doc.md §3.2。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Optional


class Executor:
    """在 McpClient 之上封装 tools/call 及单工具参数填充。"""

    def __init__(self, mcp_client: "McpClient", config: dict = None):
        """
        初始化 Executor。

        Args:
            mcp_client: §3.1 McpClient 实例，其 call_tool 可被 await。
            config: 可选 dict；须含 llm 供 LLMFactory.create；建议含 max_retries、
                backoff_base_sec、fill_arguments_max_llm_retries、
                fill_arguments_retry_backoff_sec。
        """
        self._mcp = mcp_client
        self._config = config or {}
        self._llm = self._create_llm()

    def _create_llm(self):
        """使用 config 中的 llm 段通过 LLMFactory 创建实例，失败时回退到 stub。"""
        try:
            from src.core.settings import load_settings
            from src.libs.llm.llm_factory import LLMFactory

            llm_cfg = self._config.get("llm", {})
            if llm_cfg:
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            else:
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            return LLMFactory.create(settings)
        except Exception:
            from src.libs.llm.base_llm import ChatResponse

            class _StubLLM:
                def chat(self, messages, **kwargs):
                    return ChatResponse(content="stub fill arguments", model="stub")

            return _StubLLM()

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """
        通过 McpClient.call_tool 发起 tools/call，并对失败路径做指数退避重试。

        Args:
            name: 工具名，非空字符串。
            arguments: 工具参数字典。

        Returns:
            与 §3.1 归一形状一致的 dict；重试耗尽时返回 isError=True 的结构。
        """
        if not name or not isinstance(name, str):
            raise ValueError("Tool name must be a non-empty string")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")

        max_retries = int(self._config.get("max_retries", 3))
        backoff_base = float(self._config.get("backoff_base_sec", 1.0))
        last_exception: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                print(f"[DEBUG Executor] call_tool attempt {attempt+1}/{max_retries+1}: {name}", flush=True)
                result = await self._mcp.call_tool(name, arguments)
                print(f"[DEBUG Executor] call_tool succeeded", flush=True)
                return self._normalize_call_tool_result(result)
            except Exception as exc:
                print(
                    f"[DEBUG Executor] call_tool attempt {attempt+1} failed: "
                    f"{type(exc).__name__}: {exc!r}",
                    flush=True,
                )
                last_exception = exc
                if attempt >= max_retries:
                    break
                wait = backoff_base * (2 ** attempt)
                await asyncio.sleep(wait)

        attempts = max_retries + 1
        return {
            "content": [{
                "type": "text",
                "text": (
                    f"call_tool({name!r}) failed after "
                    f"{attempts} attempts: {last_exception}"
                ),
            }],
            "isError": True,
        }

    @staticmethod
    def _normalize_call_tool_result(result: Any) -> dict:
        if not isinstance(result, dict):
            return {"content": [], "isError": True}
        normalized = dict(result)
        if "isError" not in normalized:
            normalized["isError"] = False
        if "content" not in normalized:
            normalized["content"] = []
        return normalized

    async def fill_arguments(
        self,
        tool_name: str,
        input_schema: dict,
        user_intent: str,
        prior_observation: Optional[str] = None,
    ) -> dict:
        """
        依据 input_schema 与 user_intent 调用 LLM 生成工具 arguments。

        Raises:
            ValueError: 用尽 LLM 重试仍无法得到合法 JSON object。
        """
        from src.libs.llm.base_llm import Message

        max_retries = int(self._config.get("fill_arguments_max_llm_retries", 3))
        backoff_base = float(self._config.get("fill_arguments_retry_backoff_sec", 1.0))

        system_prompt = (
            "You are a JSON generator for MCP tool arguments. "
            "Output ONLY a single valid JSON object with no markdown fences, "
            "no code blocks, and no explanatory text.\n\n"
            "CRITICAL RULES:\n"
            "- If the prior observation contains real chunk_ids (like 'doc_xxx_chunk_N' or 'xxx_NNNN_xxxxxxxx'), "
            "you MUST use those exact IDs in your output. NEVER invent fake IDs like 'placeholder', 'chunk_001', 'key_chunk' etc.\n"
            "- If you need multiple chunk_ids (e.g. for evidence_chunk_ids), extract ALL relevant IDs from prior observation, not just one.\n"
            "- If no real chunk_ids are available in prior observation, use an empty array [] for array fields.\n"
            "- For 'query' fields, use the actual user question or intent description."
        )
        schema_text = json.dumps(input_schema, ensure_ascii=False, indent=2)
        user_prompt = (
            f"Tool: {tool_name}\n"
            f"Input schema:\n{schema_text}\n\n"
            f"User intent: {user_intent}\n"
            f"Prior observation (contains real data from previous tool calls):\n{prior_observation or '(none)'}"
        )
        print(f"[DEBUG fill_arguments] tool={tool_name}, intent={user_intent[:100]}", flush=True)
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                response = self._llm.chat(messages)
                raw = getattr(response, "content", None) or str(response)
                parsed = self._parse_json_object(raw)
                if parsed is None:
                    raise ValueError(f"LLM returned non-JSON for tool {tool_name!r}")
                self._validate_against_schema(parsed, input_schema)
                return parsed
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                await asyncio.sleep(backoff_base * (2 ** attempt))

        raise ValueError(
            f"fill_arguments({tool_name!r}) failed after {max_retries + 1} attempts: {last_error}"
        )

    async def execute_task(
        self,
        task: dict,
        get_input_schema: Callable[[str], dict],
    ) -> dict:
        """
        从 task 取 tool_name → schema → fill_arguments → call_tool。

        填参或 schema 查找失败时返回 isError=True 的归一化 dict，不调用 call_tool。
        """
        raw_tool = task.get("tool_name")
        if raw_tool is not None and str(raw_tool).strip():
            tool_name = str(raw_tool).strip()
        else:
            tool_name = str(task.get("suggested_tool") or "").strip()

        if not tool_name:
            return self._error_result(
                "Task must include a non-empty tool_name or suggested_tool"
            )

        try:
            schema = get_input_schema(tool_name)
        except KeyError:
            return self._error_result(f"Tool '{tool_name}' not found in schema cache")

        try:
            arguments = await self.fill_arguments(
                tool_name=tool_name,
                input_schema=schema,
                user_intent=str(task.get("description") or ""),
                prior_observation=task.get("prior_observation") or "",
            )
        except Exception as exc:
            print(f"[DEBUG Executor] fill_arguments failed: {exc}", flush=True)
            return self._error_result(
                f"Failed to generate valid arguments for tool '{tool_name}': {exc}"
            )

        print(f"[DEBUG Executor] Calling tool {tool_name} with args: {str(arguments)[:200]}", flush=True)
        result = await self.call_tool(tool_name, arguments)

        # 打印 MCP 返回结果（截断到 500 字符）
        result_text = ""
        if isinstance(result, dict):
            content = result.get("content", [])
            if content and isinstance(content, list) and len(content) > 0:
                result_text = str(content[0].get("text", ""))[:500]
        print(f"[DEBUG Executor] Tool {tool_name} returned: {result_text}", flush=True)

        return result

    @staticmethod
    def _error_result(message: str) -> dict:
        return {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }

    @staticmethod
    def _parse_json_object(text: str) -> Optional[dict]:
        if not text or not str(text).strip():
            return None
        cleaned = str(text).strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _validate_against_schema(obj: dict, input_schema: dict) -> None:
        properties = input_schema.get("properties") or {}
        required = input_schema.get("required") or []

        for key in required:
            if key not in obj:
                raise ValueError(f"Missing required key {key!r}")

        if properties:
            extra = set(obj.keys()) - set(properties.keys())
            if extra:
                raise ValueError(f"Extra keys not in schema: {sorted(extra)}")

        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, value in obj.items():
            if key not in properties:
                continue
            expected = properties[key].get("type")
            if not expected:
                continue
            py_type = type_map.get(expected)
            if py_type and not isinstance(value, py_type):
                raise ValueError(
                    f"Key {key!r} expected type {expected}, got {type(value).__name__}"
                )
            if expected == "integer" and isinstance(value, bool):
                raise ValueError(f"Key {key!r} expected integer, got bool")
