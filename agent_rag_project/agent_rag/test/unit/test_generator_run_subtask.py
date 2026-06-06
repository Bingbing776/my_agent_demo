"""阶段 7.2 — Generator.run_subtask。见 docs/test_outline.md"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from test.helpers.contracts import assert_subtask_result

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_subtask_result_keys(generator, evaluator):
    generator._llm = MagicMock()
    generator._llm.chat.return_value = MagicMock(
        content=json.dumps({"action": "stop", "tool_name": "", "reason": "done"})
    )
    generator._config["cold_start_use_suggested_tool"] = False

    mock_executor = MagicMock()
    mock_executor.execute_task = AsyncMock(
        return_value={"content": [{"type": "text", "text": "ok"}], "isError": False}
    )

    task = {
        "id": "t1",
        "description": "retrieve info",
        "intent": "retrieve",
        "suggested_tool": "query_knowledge_hub",
    }
    result = await generator.run_subtask(
        "query",
        task,
        mock_executor,
        lambda name: {"type": "object"},
        evaluator,
        tool_names=["query_knowledge_hub"],
    )
    assert_subtask_result(result)
    assert result["task_id"] == "t1"
