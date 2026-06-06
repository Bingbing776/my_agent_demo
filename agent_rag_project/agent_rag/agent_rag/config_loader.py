"""Load agent_rag/config/settings.yaml with optional fast (llm_live) overlay."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _config_path(name: str) -> Path:
    return _CONFIG_DIR / name


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, val in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(*, fast: bool | None = None, verbose: bool | None = None) -> dict[str, Any]:
    """Load settings.yaml; merge settings.llm_live.yaml when fast=True.

    fast defaults from env: AGENT_RAG_FAST=1 (default on) unless AGENT_RAG_FULL=1.
    verbose: AGENT_RAG_VERBOSE=1 → MCP observability.log_level=DEBUG（更多检索日志）。
    """
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML required: pip install pyyaml") from exc

    base_path = _config_path("settings.yaml")
    if not base_path.exists():
        raise FileNotFoundError(f"Config not found: {base_path}")

    with base_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    if fast is None:
        if os.environ.get("AGENT_RAG_FULL", "").lower() in ("1", "true", "yes"):
            fast = False
        else:
            fast = os.environ.get("AGENT_RAG_FAST", "1").lower() in ("1", "true", "yes")

    if not fast:
        return config

    overlay_path = _config_path("settings.llm_live.yaml")
    if not overlay_path.exists():
        return config

    with overlay_path.open(encoding="utf-8") as handle:
        overlay = yaml.safe_load(handle) or {}
    config = deep_merge(config, overlay)

    if verbose is None:
        verbose = os.environ.get("AGENT_RAG_VERBOSE", "").lower() in ("1", "true", "yes")
    if verbose:
        rag = config.setdefault("rag_agent", {})
        mcp = rag.setdefault("mcp", {})
        stdio = mcp.setdefault("stdio", {})
        env = dict(stdio.get("env") or {})
        env["MODULAR_RAG_LOG_LEVEL"] = "DEBUG"
        stdio["env"] = env
    return config


def config_mode_label(fast: bool) -> str:
    return "fast (settings.llm_live.yaml)" if fast else "full (settings.yaml only)"
