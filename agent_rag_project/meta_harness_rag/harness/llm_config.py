"""Harness 自有 LLM 配置（仅读 config/harness.yaml 的 llm 段，与 agent_rag 无关）。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class HarnessLLMConfig:
    """Harness 三 Agent 共用的 LLM 连接参数。"""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    api_key: str | None = None
    base_url: str | None = None
    api_version: str | None = None
    azure_endpoint: str | None = None
    deployment_name: str | None = None

    @classmethod
    def from_harness_cfg(cls, harness_cfg: dict, *, section: str = "llm") -> HarnessLLMConfig:
        raw = harness_cfg.get(section) or {}
        if not isinstance(raw, dict):
            raw = {}
        provider = str(raw.get("provider", "custom")).strip().lower()
        model = str(raw.get("model", "")).strip()
        if not model:
            raise ValueError(
                f"Harness LLM 未配置 model。请在 meta_harness_rag/config/harness.yaml 的 {section} 段设置。"
            )
        return cls(
            provider=provider,
            model=model,
            temperature=float(raw.get("temperature", 0.0)),
            max_tokens=int(raw.get("max_tokens", 4096)),
            api_key=_resolve_api_key(raw),
            base_url=_optional_str(raw.get("base_url")),
            api_version=_optional_str(raw.get("api_version")),
            azure_endpoint=_optional_str(raw.get("azure_endpoint")),
            deployment_name=_optional_str(raw.get("deployment_name")),
        )

    def resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        env = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        if env:
            return env
        raise ValueError(
            "Harness LLM 缺少 api_key。请在 harness.yaml 的 llm.api_key 或环境变量 OPENAI_API_KEY 中设置。"
        )

    def require_base_url(self) -> str:
        if self.base_url and str(self.base_url).strip():
            return str(self.base_url).strip()
        raise ValueError(
            "Harness Custom HTTP 需要 llm.base_url（完整聊天 endpoint）。"
            "请在 meta_harness_rag/config/harness.yaml 的 llm 段配置。"
        )


def _optional_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _resolve_api_key(raw: dict) -> str | None:
    k = raw.get("api_key")
    if k is not None and str(k).strip():
        return str(k).strip()
    return None


def settings_namespace(cfg: HarnessLLMConfig) -> Any:
    """供父项目 LLMFactory / CustomLLM 使用的轻量 settings 对象。"""
    llm = SimpleNamespace(
        provider=cfg.provider,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        api_version=cfg.api_version,
        azure_endpoint=cfg.azure_endpoint,
        deployment_name=cfg.deployment_name,
    )
    return SimpleNamespace(llm=llm)
