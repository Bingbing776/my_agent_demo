"""Phase 5.11 - MemoryManager.retrieve_context. See docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_returns_str(memory_manager):
    """retrieve_context returns str; empty memory returns empty; populated memory returns non-empty."""
    # Empty/None query must yield empty string
    assert memory_manager.retrieve_context("") == ""
    assert memory_manager.retrieve_context(None) == ""

    # Empty memory must yield empty string
    ctx = memory_manager.retrieve_context("q")
    assert isinstance(ctx, str)
    assert ctx == "", "empty memory should return empty context string"

    # Populate short-term memory with realistic MCP result data
    from test.helpers.samples import sample_mcp_tool_call_result
    result = sample_mcp_tool_call_result()
    memory_manager.add_short_term("TOPMOST features", result)

    # retrieve_context must return a non-empty string when memory has items
    ctx2 = memory_manager.retrieve_context("TOPMOST")
    assert isinstance(ctx2, str)
    assert len(ctx2) > 0, "retrieve_context with populated memory should return non-empty string"
