"""仅导入 agent_rag/ 产品代码（tech_doc §1–§7）。勿指向 meta_harness_rag/harness/。"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import pytest

# (module_path, attr_name)
PATHS: dict[str, list[tuple[str, str]]] = {
    "MemoryManager": [
        ("agent_rag.memory.memory_manager", "MemoryManager"),
    ],
    "ContextManager": [
        ("agent_rag.context.context_manager", "ContextManager"),
    ],
    "McpClient": [
        ("agent_rag.mcp.mcp_client", "McpClient"),
    ],
    "Executor": [
        ("agent_rag.mcp.executor", "Executor"),
    ],
    "PlannerAgent": [
        ("agent_rag.agents.planner", "PlannerAgent"),
    ],
    "Evaluator": [
        ("agent_rag.agents.evaluator", "Evaluator"),
    ],
    "Generator": [
        ("agent_rag.agents.generator", "Generator"),
    ],
    "RagOrchestrator": [
        ("agent_rag.orchestrator.rag_orchestrator", "RagOrchestrator"),
    ],
}


def import_class(name: str) -> type[Any]:
    for mod_path, attr in PATHS.get(name, []):
        try:
            mod = importlib.import_module(mod_path)
            return getattr(mod, attr)
        except (ImportError, AttributeError):
            continue
    pytest.skip(f"{name} not implemented yet in agent_rag/ (see meta_harness_rag/docs/tech_doc.md)")


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into a copy of base."""
    out = dict(base)
    for key, val in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


def load_config() -> dict[str, Any]:
    path = _config_dir() / "settings.yaml"
    if not path.exists():
        pytest.skip("settings.yaml not found")
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML required for config tests")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config_llm_live() -> dict[str, Any]:
    """Base settings.yaml + settings.llm_live.yaml overlay."""
    base = load_config()
    overlay_path = _config_dir() / "settings.llm_live.yaml"
    if not overlay_path.exists():
        return base
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML required for config tests")
    with open(overlay_path, encoding="utf-8") as f:
        overlay = yaml.safe_load(f) or {}
    return deep_merge(base, overlay)


def is_llm_live_requested() -> bool:
    if os.environ.get("AGENT_RAG_LLM_LIVE", "").lower() in ("1", "true", "yes"):
        return True
    argv = " ".join(os.environ.get("PYTEST_ADDOPTS", "").split() + __import__("sys").argv)
    if "-m llm_live" in argv.replace("=", " "):
        return True
    if " llm_live" in argv and "not llm_live" not in argv:
        return True
    return False
