"""阶段 3.9 — RagOrchestrator._synthesize_final_answer。见 docs/test_outline.md"""
import pytest
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_returns_str(orchestrator):
    orchestrator._llm = MagicMock()
    orchestrator._llm.chat.return_value = MagicMock(content="final synthesized answer")
    result = await orchestrator._synthesize_final_answer("q", "evidence")
    assert isinstance(result, str)
    assert "final" in result.lower() or result
