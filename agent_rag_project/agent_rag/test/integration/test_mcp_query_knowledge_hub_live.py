"""阶段 4.5 — query_knowledge_hub 真调用。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.mcp]

def test_live_call():
    pytest.skip("requires MCP stdio")
