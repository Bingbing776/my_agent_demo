"""阶段 3.6 — Generator.choose_next_action。见 docs/test_outline.md"""
import json

import pytest
from unittest.mock import MagicMock

from test.helpers.contracts import assert_next_action_result

pytestmark = [pytest.mark.unit]


def _mock_llm(content: str):
    mock = MagicMock()
    mock.chat.return_value = MagicMock(content=content)
    return mock


@pytest.mark.asyncio
async def test_action_enum(generator):
    generator._llm = _mock_llm(json.dumps({"action": "stop", "tool_name": "", "reason": "done"}))
    result = await generator.choose_next_action(
        "q",
        {"description": "d", "intent": "retrieve"},
        [],
        tool_names=["query_knowledge_hub"],
    )
    assert_next_action_result(result)
    assert result["action"] == "stop"
