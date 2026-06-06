"""配置加载：Harness 与 RAG 产品分文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_PKG_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_HARNESS = _PKG_ROOT / "config" / "harness.yaml"
_DEFAULT_PRODUCT_ROOT = _PKG_ROOT.parent / "agent_rag"
_DEFAULT_RAG_SETTINGS = _DEFAULT_PRODUCT_ROOT / "config" / "settings.yaml"


def resolve_product_root(harness_cfg: dict, package_root: Path) -> Path:
    """RAG 产品根目录（含 test/、config/settings.yaml、agent_rag/ 包）。"""
    raw = harness_cfg.get("product_root", "../agent_rag")
    path = Path(raw)
    if not path.is_absolute():
        path = (package_root / path).resolve()
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError as e:
        raise ImportError("PyYAML is required: pip install pyyaml") from e
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_harness_config(path: Path | None = None) -> dict[str, Any]:
    """Harness 专用：config/harness.yaml（根级键，无 harness: 包裹）。"""
    return _load_yaml(path or _DEFAULT_HARNESS)


def load_rag_settings(path: Path | None = None) -> dict[str, Any]:
    """RAG 产品 / 父项目 MCP：config/settings.yaml（含 rag_agent、llm、embedding 等）。"""
    return _load_yaml(path or _DEFAULT_RAG_SETTINGS)


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """向后兼容：等同于 load_rag_settings（pytest 契约等仍用此名）。"""
    return load_rag_settings(path)


def harness_config(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """向后兼容：若传入整文件 dict 且含 harness 键则取之，否则读 harness.yaml。"""
    if settings and "harness" in settings:
        return settings.get("harness") or {}
    return load_harness_config()


def rag_agent_config(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or load_rag_settings()
    return settings.get("rag_agent") or {}
