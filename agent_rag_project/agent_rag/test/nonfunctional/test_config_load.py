"""阶段 10.1 — 配置加载。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_loads():
    from test.helpers.imports import load_config; cfg = load_config(); assert "llm" in cfg or "rag_agent" in cfg
