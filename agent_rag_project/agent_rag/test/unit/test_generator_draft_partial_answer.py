"""阶段 3.7 — Generator.draft_partial_answer。见 docs/test_outline.md"""
import pytest
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_returns_str(generator):
    mock = MagicMock()
    mock.chat.return_value = MagicMock(content="partial draft about TOPMOST")
    generator._llm = mock
    result = await generator.draft_partial_answer(
        "What is TOPMOST?",
        {"description": "Find features", "intent": "retrieve"},
        "query_knowledge_hub: 3 hits",
    )
    assert isinstance(result, str)
    assert result
