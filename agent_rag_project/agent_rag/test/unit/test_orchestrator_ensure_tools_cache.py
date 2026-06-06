"""阶段 8.1.2 — RagOrchestrator._ensure_tools_cache。见 docs/test_outline.md"""
import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_idempotent(orchestrator):
    tool = MagicMock()
    tool.name = "query_knowledge_hub"
    tool.description = "search"
    tool.inputSchema = {"type": "object"}
    orchestrator._mcp_session = MagicMock()
    orchestrator._mcp_session.list_tools = AsyncMock(return_value=MagicMock(tools=[tool]))
    await orchestrator._ensure_tools_cache()
    assert "query_knowledge_hub" in orchestrator._tools_by_name
    await orchestrator._ensure_tools_cache()
    assert len(orchestrator._tools_by_name) == 1
