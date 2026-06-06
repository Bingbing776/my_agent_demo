"""§7 — RagOrchestrator 功能门禁验收。"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from test.helpers.contracts import assert_global_answer_readiness

pytestmark = [pytest.mark.gate]


def test_orchestrator_init(orchestrator):
    assert orchestrator is not None
    assert hasattr(orchestrator, "_planner")
    assert hasattr(orchestrator, "_generator")
    assert hasattr(orchestrator, "_evaluator")


@pytest.mark.asyncio
async def test_ensure_tools_cache(orchestrator):
    tool = MagicMock()
    tool.name = "query_knowledge_hub"
    tool.description = "search hub"
    tool.inputSchema = {"type": "object"}
    orchestrator._mcp_session = MagicMock()
    orchestrator._mcp_session.list_tools = AsyncMock(return_value=MagicMock(tools=[tool]))
    await orchestrator._ensure_tools_cache()
    assert "query_knowledge_hub" in orchestrator._tools_by_name


def test_build_tool_index_text(orchestrator):
    orchestrator._tools_by_name = {
        "query_knowledge_hub": {"description": "Search documents"},
    }
    text = orchestrator.build_tool_index_text()
    assert "query_knowledge_hub" in text


@pytest.mark.asyncio
async def test_check_global_answer_readiness(orchestrator):
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
    result = await orchestrator._check_global_answer_readiness(
        "What is TOPMOST?",
        "## t1 (success)\nTOPMOST is a toolkit.",
    )
    assert_global_answer_readiness(result)


@pytest.mark.asyncio
async def test_synthesize_final_answer_returns_dict(orchestrator):
    orchestrator._llm = MagicMock()
    orchestrator._llm.chat.return_value = MagicMock(content="TOPMOST is a topic modeling toolkit.")
    text = await orchestrator._synthesize_final_answer(
        "What is TOPMOST?",
        "## t1 (success)\ndraft evidence",
    )
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.llm_live
def test_real_orchestrator_answer(real_llm, config):
    import asyncio

    from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
    from test.helpers.contracts import assert_answer_result

    async def _run() -> dict:
        orch = RagOrchestrator(config=config)
        orch._planner._llm = real_llm
        orch._evaluator._llm = real_llm
        orch._generator._llm = real_llm
        orch._llm = real_llm
        return await orch.answer("TOPMOST 主要解决什么问题？")

    result = asyncio.run(_run())
    assert_answer_result(result)
    assert len(result["text"].strip()) > 10


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_check_global_readiness_prompt(real_llm, config):
    from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
    from test.helpers.contracts import assert_global_answer_readiness
    from test.helpers.samples import sample_subtask_result

    orch = RagOrchestrator(config=config)
    orch._llm = real_llm
    bundle = orch._build_final_evidence_bundle(
        [
            sample_subtask_result(
                task_id="t1",
                draft_text="TOPMOST addresses inconsistent evaluation in topic modeling.",
            )
        ]
    )
    result = await orch._check_global_answer_readiness(
        "What problem does TOPMOST solve?",
        bundle,
        context="",
    )
    assert_global_answer_readiness(result)
