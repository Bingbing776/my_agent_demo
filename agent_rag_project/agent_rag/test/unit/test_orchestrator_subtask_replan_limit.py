"""子任务 replan / 子任务总数上限。"""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_subtask_replan_round_cap(orchestrator):
    rag = orchestrator._config.setdefault("rag_agent", {})
    rag.setdefault("mcp", {})["stdio"] = None
    orch_cfg = rag.setdefault("orchestrator", {})
    orch_cfg["max_subtask_replan_rounds"] = 2
    orch_cfg["max_subtasks_total"] = 50
    orch_cfg["max_global_replan_rounds"] = 0
    orch_cfg["allow_final_on_insufficient_evidence"] = True

    replan_calls: list[int] = []

    def _replan(*_args, **_kwargs):
        replan_calls.append(1)
        return [
            {
                "id": f"replan-{len(replan_calls)}",
                "description": "retry",
                "suggested_tool": "query_knowledge_hub",
            }
        ]

    orchestrator._planner.plan = lambda *_a, **_k: [
        {"id": "initial", "description": "start", "suggested_tool": "query_knowledge_hub"}
    ]
    orchestrator._planner.replan = _replan
    orchestrator._planner.load_routing_hint = lambda: ""

    async def _always_needs_replan(*_args, **_kwargs):
        return {
            "task_id": "t",
            "status": "needs_replan",
            "observation_for_replan": "need more evidence",
            "tool_trace": [],
            "draft_text": "partial",
        }

    orchestrator._generator.run_subtask = _always_needs_replan
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
    assert len(replan_calls) == 2


@pytest.mark.asyncio
async def test_max_subtasks_total_cap(orchestrator):
    rag = orchestrator._config.setdefault("rag_agent", {})
    rag.setdefault("mcp", {})["stdio"] = None
    orch_cfg = rag.setdefault("orchestrator", {})
    orch_cfg["max_subtask_replan_rounds"] = 10
    orch_cfg["max_subtasks_total"] = 3
    orch_cfg["max_global_replan_rounds"] = 0
    orch_cfg["allow_final_on_insufficient_evidence"] = True

    run_count = 0

    def _replan(*_args, **_kwargs):
        return [
            {"id": "extra", "description": "more", "suggested_tool": "query_knowledge_hub"}
        ]

    orchestrator._planner.plan = lambda *_a, **_k: [
        {"id": "initial", "description": "start", "suggested_tool": "query_knowledge_hub"}
    ]
    orchestrator._planner.replan = _replan
    orchestrator._planner.load_routing_hint = lambda: ""

    async def _needs_replan(*_args, **_kwargs):
        nonlocal run_count
        run_count += 1
        return {
            "task_id": "t",
            "status": "needs_replan",
            "observation_for_replan": "again",
            "tool_trace": [],
            "draft_text": "",
        }

    orchestrator._generator.run_subtask = _needs_replan
    orchestrator._ensure_tools_cache = AsyncMock()
    orchestrator._tools_by_name = {"query_knowledge_hub": {}}
    orchestrator._build_final_evidence_bundle = lambda _results: "evidence"
    orchestrator._check_global_answer_readiness = AsyncMock(
        return_value={"sufficient_for_answer": True, "need_replan": False}
    )
    orchestrator._synthesize_final_answer = AsyncMock(return_value="done")
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

    assert result["text"] == "done"
    assert run_count == 3
