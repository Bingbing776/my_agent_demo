"""检索结果无新增证据时停止继续检索。"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_extract_evidence_ids(orchestrator):
    text = (
        "chunk `9a08dfd1_0007_2c9d39fa` from doc_4e6d9b8d4efd6759; "
        "also 73743f66_0018_5b585ea7"
    )
    ids = orchestrator._extract_evidence_ids(text)
    assert "9a08dfd1_0007_2c9d39fa" in ids
    assert "73743f66_0018_5b585ea7" in ids
    assert "doc_4e6d9b8d4efd6759" in ids


@pytest.mark.asyncio
async def test_stale_retrieval_stops_replan(orchestrator):
    rag = orchestrator._config.setdefault("rag_agent", {})
    rag.setdefault("mcp", {})["stdio"] = None
    orch_cfg = rag.setdefault("orchestrator", {})
    orch_cfg["max_subtask_replan_rounds"] = 5
    orch_cfg["max_subtasks_total"] = 20
    orch_cfg["max_global_replan_rounds"] = 0
    orch_cfg["allow_final_on_insufficient_evidence"] = True
    orch_cfg["skip_replan_when_no_new_evidence"] = True
    orch_cfg["no_new_evidence_replan_streak"] = 1

    chunk_summary = (
        "## 检索结果\n"
        "### [1] 结果 1\n"
        "> TOPMOST toolkit\n"
        "chunk_id: 9a08dfd1_0007_2c9d39fa"
    )
    replan_calls: list[int] = []
    run_count = 0

    def _replan(*_args, **_kwargs):
        replan_calls.append(1)
        return [
            {
                "id": "retry",
                "description": "search again",
                "suggested_tool": "query_knowledge_hub",
            }
        ]

    orchestrator._planner.plan = lambda *_a, **_k: [
        {"id": "initial", "description": "search", "suggested_tool": "query_knowledge_hub"}
    ]
    orchestrator._planner.replan = _replan
    orchestrator._planner.load_routing_hint = lambda: ""

    async def _retrieve_then_replan(*_args, **_kwargs):
        nonlocal run_count
        run_count += 1
        return {
            "task_id": "t",
            "status": "needs_replan",
            "observation_for_replan": "need more",
            "tool_trace": [
                {
                    "tool_name": "query_knowledge_hub",
                    "ok": True,
                    "summary": chunk_summary,
                }
            ],
            "draft_text": "",
        }

    orchestrator._generator.run_subtask = _retrieve_then_replan
    orchestrator._ensure_tools_cache = AsyncMock()
    orchestrator._tools_by_name = {"query_knowledge_hub": {}}
    orchestrator._build_final_evidence_bundle = lambda _results: "evidence"
    orchestrator._check_global_answer_readiness = AsyncMock(
        return_value={"sufficient_for_answer": True, "need_replan": False}
    )
    orchestrator._synthesize_final_answer = AsyncMock(return_value="final answer")
    orchestrator._memory.retrieve_context = lambda *_a, **_k: ""
    orchestrator._context.get_relevant_context = lambda *_a, **_k: ""
    orchestrator._memory.add_short_term = lambda *_a, **_k: None
    orchestrator._context.update_context = lambda *_a, **_k: None

    mock_session = MagicMock()
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
    orchestrator._mcp_session = mock_session
    from agent_rag.mcp.executor import Executor
    from agent_rag.mcp.mcp_client import McpClient

    orchestrator._executor = Executor(
        mcp_client=McpClient(session=mock_session, config=rag),
        config=rag,
    )

    result = await orchestrator.answer("test query")

    assert result["text"] == "final answer"
    assert run_count == 2
    assert len(replan_calls) == 1
