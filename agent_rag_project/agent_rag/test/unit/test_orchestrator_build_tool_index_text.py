"""阶段 2.4.4 — RagOrchestrator.build_tool_index_text。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_lists_all_tools(orchestrator):
    orchestrator._tools_by_name = {"a": {"description": "d"}}; t = orchestrator.build_tool_index_text(); assert "- a:" in t
