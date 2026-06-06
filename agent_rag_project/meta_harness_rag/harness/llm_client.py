"""Harness 专用 LLM 客户端（配置来自 harness.yaml，经 LLMFactory 实例化）。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, NamedTuple

from harness.llm_config import HarnessLLMConfig, settings_namespace

_PKG_ROOT = Path(__file__).resolve().parents[1]


class HarnessLLM(NamedTuple):
    llm: Any
    Message: type
    model: str
    provider: str
    config: HarnessLLMConfig


def _mcp_repo_root() -> Path:
    candidates = [
        _PKG_ROOT.parent / "mcp_rag",
        _PKG_ROOT / "mcp_rag",
        _PKG_ROOT.parent,
    ]
    for root in candidates:
        if (root / "src" / "libs" / "llm" / "llm_factory.py").is_file():
            return root.resolve()
    raise FileNotFoundError(
        "未找到 mcp_rag（需含 src/libs/llm）。"
        "请将子项目放在 meta_harness_rag 同级目录。"
    )


def _ensure_repo_on_path(repo_root: Path) -> None:
    s = str(repo_root)
    if s not in sys.path:
        sys.path.insert(0, s)


def _factory_base_url(base_url: str | None) -> str | None:
    """OpenAILLM/DeepSeekLLM 会自行拼接 ``/chat/completions``，勿传完整 endpoint。"""
    if not base_url or not str(base_url).strip():
        return None
    u = str(base_url).strip().rstrip("/")
    suffix = "/chat/completions"
    if u.endswith(suffix):
        return u[: -len(suffix)]
    return u


def resolve_factory_base_url(provider: str, base_url: str | None) -> str | None:
    """Return ``base_url`` for ``LLMFactory.create`` kwargs."""
    if not base_url or not str(base_url).strip():
        return None
    if str(provider).strip().lower() == "custom":
        # CustomLLM POSTs to base_url as the complete endpoint (no path appending).
        return str(base_url).strip()
    return _factory_base_url(base_url)


def create_harness_llm(harness_cfg: dict, package_root: Path | None = None) -> HarnessLLM | None:
    """
    从 ``config/harness.yaml`` 的 ``llm`` 段创建 LLM（不读取 agent_rag 的 settings）。

    ``harness_cfg["llm_enabled"]`` 为 false 时返回 None。
    """
    if harness_cfg.get("llm_enabled") is False:
        return None

    llm_cfg = HarnessLLMConfig.from_harness_cfg(harness_cfg)

    repo_root = _mcp_repo_root()
    _ensure_repo_on_path(repo_root)

    try:
        from src.libs.llm import Message  # noqa: F401 — 触发 register_provider
        from src.libs.llm.llm_factory import LLMFactory
    except ImportError as e:
        raise RuntimeError(f"无法导入父项目 LLM 模块: {e}") from e

    settings = settings_namespace(llm_cfg)
    factory_kwargs: dict[str, Any] = {}
    normalized_base = resolve_factory_base_url(llm_cfg.provider, llm_cfg.base_url)
    if normalized_base:
        factory_kwargs["base_url"] = normalized_base
    try:
        factory_kwargs["api_key"] = llm_cfg.resolved_api_key()
    except ValueError:
        pass
    try:
        llm = LLMFactory.create(settings, **factory_kwargs)
    except Exception as e:
        raise RuntimeError(
            f"LLMFactory 创建失败 (provider={llm_cfg.provider}): {e}"
        ) from e

    return HarnessLLM(
        llm=llm,
        Message=Message,
        model=llm_cfg.model,
        provider=llm_cfg.provider,
        config=llm_cfg,
    )
