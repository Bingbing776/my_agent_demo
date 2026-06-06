"""Harness 专用 HTTP 客户端（配置来自 harness.yaml，按 CustomLLM 直连 base_url）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.llm_config import HarnessLLMConfig
from harness.llm_helpers import agent_max_tokens, agent_temperature


class HarnessLLMHttpError(RuntimeError):
    pass


def openai_tool_schemas() -> list[dict[str, Any]]:
    """OpenAI Chat Completions 的 tools 定义（Evaluator 文件工具）。"""
    def fn(name: str, description: str, props: dict, required: list[str]) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }

    return [
        fn(
            "read_file",
            "读取 agent_rag 或 Harness 允许目录下的相对路径文件",
            {"rel_path": {"type": "string", "description": "如 test/conftest.py"}},
            ["rel_path"],
        ),
        fn(
            "list_dir",
            "列出允许目录下的条目",
            {"rel_path": {"type": "string", "description": "目录相对路径，默认 test"}},
            [],
        ),
        fn(
            "grep_in_file",
            "在单个文件内正则搜索",
            {
                "rel_path": {"type": "string"},
                "pattern": {"type": "string", "description": "正则表达式"},
            },
            ["rel_path", "pattern"],
        ),
    ]


@dataclass
class HarnessCustomHttp:
    """
    与 ``CustomLLM`` 相同：``base_url`` 为完整聊天地址，不拼接 ``/chat/completions``。
    支持请求体 ``tools`` / 响应 ``tool_calls``。
    """

    url: str
    api_key: str
    model: str
    provider: str
    default_temperature: float
    default_max_tokens: int
    timeout_sec: float = 120.0

    @classmethod
    def from_llm_config(
        cls, llm_cfg: HarnessLLMConfig, harness_cfg: dict, agent_key: str = "evaluator"
    ) -> HarnessCustomHttp:
        ev = harness_cfg.get(agent_key) or {}
        llm_sec = harness_cfg.get("llm") or {}
        timeout = float(
            ev.get("http_timeout_sec")
            or llm_sec.get("http_timeout_sec")
            or 120.0
        )
        return cls(
            url=llm_cfg.require_base_url(),
            api_key=llm_cfg.resolved_api_key(),
            model=llm_cfg.model,
            provider=llm_cfg.provider,
            default_temperature=llm_cfg.temperature,
            default_max_tokens=llm_cfg.max_tokens,
            timeout_sec=timeout,
        )

    def _temperature(self, harness_cfg: dict, agent_key: str) -> float:
        return agent_temperature(harness_cfg, agent_key)

    def _max_tokens(self, harness_cfg: dict, agent_key: str) -> int:
        return agent_max_tokens(harness_cfg, agent_key)

    def chat_completions(
        self,
        messages: list[dict[str, Any]],
        *,
        harness_cfg: dict,
        agent_key: str = "evaluator",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = "auto",
    ) -> dict[str, Any]:
        """POST 到 base_url（CustomLLM 语义）。"""
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self._temperature(harness_cfg, agent_key),
            "max_tokens": self._max_tokens(harness_cfg, agent_key),
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

        try:
            with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
                response = client.post(self.url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise HarnessLLMHttpError(f"HTTP 超时 ({self.timeout_sec}s): {self.url}") from e
        except httpx.RequestError as e:
            raise HarnessLLMHttpError(f"HTTP 连接失败: {e}") from e

        if response.status_code != 200:
            raise HarnessLLMHttpError(f"HTTP {response.status_code}: {response.text[:2000]}")

        ct = response.headers.get("content-type", "")
        if "application/json" not in ct:
            raise HarnessLLMHttpError(
                f"期望 JSON，收到 content-type={ct}，预览: {response.text[:300]}"
            )
        return response.json()

    @staticmethod
    def _choice_message(data: dict[str, Any]) -> dict[str, Any]:
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as e:
            raise HarnessLLMHttpError(f"响应缺少 choices[0].message: {e}") from e
        finish_reason = choice.get("finish_reason", "")
        if finish_reason == "length":
            logging.getLogger(__name__).warning(
                "LLM 输出被截断 (finish_reason=length)，当前 max_tokens 可能不够。"
                " 模型: %s",
                data.get("model", "unknown"),
            )
        try:
            return choice["message"]
        except (KeyError, TypeError) as e:
            raise HarnessLLMHttpError(f"响应缺少 choices[0].message: {e}") from e


def create_harness_custom_http(
    harness_cfg: dict,
    package_root: Path | None = None,
    *,
    agent_key: str = "evaluator",
) -> HarnessCustomHttp | None:
    """
    从 ``harness.yaml`` 的 ``fc_llm`` 或 ``llm`` 段创建 HTTP 客户端。
    优先使用 ``fc_llm``（Function Calling 专用），不存在时回退 ``llm``。
    ``evaluator.llm_transport`` 为 ``factory`` 时返回 None。
    """
    _ = package_root  # 保留参数以兼容旧调用；配置不再依赖外部路径

    ev_cfg = harness_cfg.get(agent_key) or {}
    transport = str(
        ev_cfg.get("llm_transport") or harness_cfg.get("llm_transport") or "custom_http"
    ).lower()
    if transport in ("factory", "llm_factory", "none"):
        return None
    if harness_cfg.get("llm_enabled") is False:
        return None

    # 优先读取 fc_llm 段（Function Calling 专用），不存在时回退 llm 段
    section = "fc_llm" if harness_cfg.get("fc_llm") else "llm"
    llm_cfg = HarnessLLMConfig.from_harness_cfg(harness_cfg, section=section)
    try:
        return HarnessCustomHttp.from_llm_config(llm_cfg, harness_cfg, agent_key)
    except ValueError as e:
        raise HarnessLLMHttpError(str(e)) from e
