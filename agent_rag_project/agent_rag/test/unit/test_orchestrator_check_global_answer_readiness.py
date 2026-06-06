"""阶段 3.8 — RagOrchestrator._check_global_answer_readiness。见 docs/test_outline.md"""
import json

import pytest
from unittest.mock import MagicMock

from test.helpers.contracts import assert_global_answer_readiness

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_five_keys(orchestrator):
    orchestrator._llm = MagicMock()
    orchestrator._llm.chat.return_value = MagicMock(
        content=json.dumps(
            {
                "sufficient_for_answer": True,
                "need_replan": False,
                "issues": [],
                "observation_for_replan": "",
                "suggested_retrieval_changes": [],
            }
        )
    )
    result = await orchestrator._check_global_answer_readiness("q", "evidence bundle")
    assert_global_answer_readiness(result)
