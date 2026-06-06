"""三 Agent 共用的 LLM 调用与 JSON 解析。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from harness.llm_client import HarnessLLM

logger = logging.getLogger(__name__)

# agent_key: "planner" | "generator" | "evaluator" 或 harness.yaml 中的子段名


def agent_temperature(harness_cfg: dict, agent_key: str, default: float = 0.0) -> float:
    agent = harness_cfg.get(agent_key) or {}
    if "temperature" in agent:
        return float(agent["temperature"])
    return float((harness_cfg.get("llm") or {}).get("temperature", default))


def agent_max_tokens(harness_cfg: dict, agent_key: str, default: int = 4096) -> int:
    agent = harness_cfg.get(agent_key) or {}
    if "max_tokens" in agent:
        return int(agent["max_tokens"])
    return int((harness_cfg.get("llm") or {}).get("max_tokens", default))


def _extract_finish_reason(resp: Any) -> str:
    raw = getattr(resp, "raw_response", None)
    if not isinstance(raw, dict):
        return ""
    try:
        return str(raw["choices"][0].get("finish_reason") or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _log_chat_usage(
    resp: Any,
    *,
    harness_cfg: dict,
    agent_key: str,
) -> None:
    """记录 finish_reason / token 用量，便于判断 max_tokens 是否导致输出截断。"""
    finish_reason = _extract_finish_reason(resp)
    max_tokens = agent_max_tokens(harness_cfg, agent_key)
    model = getattr(resp, "model", "") or ""
    content = getattr(resp, "content", None) or ""
    usage = getattr(resp, "usage", None)
    completion_tokens: int | None = None
    if isinstance(usage, dict):
        try:
            completion_tokens = int(usage.get("completion_tokens"))
        except (TypeError, ValueError):
            completion_tokens = None

    if finish_reason == "length":
        logger.warning(
            "LLM 输出被截断 finish_reason=length agent=%s model=%s max_tokens=%s "
            "completion_tokens=%s content_chars=%s",
            agent_key,
            model,
            max_tokens,
            completion_tokens,
            len(content),
        )
        return

    logger.info(
        "LLM chat agent=%s model=%s finish_reason=%s max_tokens=%s "
        "completion_tokens=%s content_chars=%s",
        agent_key,
        model,
        finish_reason or "(unknown)",
        max_tokens,
        completion_tokens,
        len(content),
    )


def chat(
    bundle: HarnessLLM,
    *,
    system: str,
    user: str,
    harness_cfg: dict,
    agent_key: str,
) -> str:
    Message = bundle.Message
    max_tokens = agent_max_tokens(harness_cfg, agent_key)
    resp = bundle.llm.chat(
        [
            Message(role="system", content=system),
            Message(role="user", content=user),
        ],
        temperature=agent_temperature(harness_cfg, agent_key),
        max_tokens=max_tokens,
    )
    _log_chat_usage(resp, harness_cfg=harness_cfg, agent_key=agent_key)
    return (getattr(resp, "content", None) or str(resp)).strip()


def strip_python_fence(text: str) -> str:
    """从 LLM 回复中提取 Python 源码（去掉 ```python 围栏）。"""
    t = text.strip()
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if t.startswith("```"):
        return re.sub(r"^```\w*\n?", "", t).strip().rstrip("`").strip()
    return t


def strip_json_fence(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        return m.group(1).strip()
    return t


def parse_json_object(text: str) -> dict[str, Any]:
    raw = strip_json_fence(text)
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("expected JSON object")
    return obj


def parse_json_array(text: str) -> list[Any]:
    raw = strip_json_fence(text)
    arr = json.loads(raw)
    if not isinstance(arr, list):
        raise ValueError("expected JSON array")
    return arr
