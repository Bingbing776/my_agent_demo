"""Phase 4.3 -- PlannerAgent.plan. See docs/test_outline.md"""
import json
import pytest
from unittest.mock import MagicMock

from agent_rag.agents.planner import PlannerAgent

pytestmark = [pytest.mark.unit]

TOOL_INDEX = (
    "- query_knowledge_hub: Search knowledge base\n"
    "- read_chunk: Read a chunk by ID\n"
    "- get_neighbor_chunks: Get surrounding chunks\n"
)


def _mock_llm(content: str):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = content
    mock_llm.chat.return_value = mock_response
    return mock_llm


def _call_plan(planner_agent, *, llm_content, context="Previous conversation", routing_hint="Use query_knowledge_hub"):
    original_llm = planner_agent._llm
    planner_agent._llm = _mock_llm(llm_content)
    try:
        return planner_agent.plan(
            query="What is TOPMOST?",
            context=context,
            tool_index=TOOL_INDEX,
            routing_hint=routing_hint,
        )
    finally:
        planner_agent._llm = original_llm


def test_parses_json_array(planner_agent):
    """plan() correctly parses a valid JSON array from LLM and returns list[dict] with required keys."""
    valid_plan = [
        {
            "id": "t1",
            "description": "Search knowledge hub for TOPMOST features",
            "intent": "retrieve",
            "suggested_tool": "query_knowledge_hub",
            "done_criteria": "At least 3 relevant chunks found",
            "replan_triggers": "No results returned",
        },
        {
            "id": "t2",
            "description": "Read the most relevant chunk for details",
            "intent": "read",
            "suggested_tool": "read_chunk",
            "done_criteria": "Chunk content retrieved",
            "replan_triggers": "Chunk not found or empty",
        },
    ]

    result = _call_plan(planner_agent, llm_content=json.dumps(valid_plan))

    assert isinstance(result, list)
    assert len(result) == 2
    for item in result:
        assert isinstance(item, dict)
        assert "id" in item
        assert "description" in item
        assert "intent" in item

    assert result[0]["id"] == "t1"
    assert result[0]["suggested_tool"] == "query_knowledge_hub"
    assert result[0]["done_criteria"] == "At least 3 relevant chunks found"
    assert result[1]["id"] == "t2"
    assert result[1]["suggested_tool"] == "read_chunk"


def test_plan_llm_with_markdown_fence(planner_agent):
    """plan() should strip markdown code fences from the LLM response before JSON parsing."""
    valid_plan = [{"id": "a", "description": "d", "intent": "i", "suggested_tool": "query_knowledge_hub"}]
    json_str = json.dumps(valid_plan)
    fenced_response = f"```json\n{json_str}\n```"

    result = _call_plan(planner_agent, llm_content=fenced_response)

    assert result == valid_plan


def test_plan_invalid_json_returns_fallback(planner_agent):
    """Non-JSON LLM output should trigger fallback plan."""
    result = _call_plan(planner_agent, llm_content="not valid json at all")

    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["id"] == "fallback-clarify"
    assert "description" in result[0]
    assert "intent" in result[0]


def test_plan_llm_exception_returns_fallback(planner_agent):
    """LLM chat failure should trigger fallback plan."""
    original_llm = planner_agent._llm
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM unavailable")
    planner_agent._llm = mock_llm
    try:
        result = planner_agent.plan(
            query="What is TOPMOST?",
            context="ctx",
            tool_index=TOOL_INDEX,
            routing_hint="hint",
        )
    finally:
        planner_agent._llm = original_llm

    assert result[0]["id"] == "fallback-clarify"


def test_plan_missing_required_keys_returns_fallback(planner_agent):
    """Items missing id/description/intent should trigger fallback."""
    bad_plan = [{"id": "t1", "description": "only partial keys"}]
    result = _call_plan(planner_agent, llm_content=json.dumps(bad_plan))

    assert result[0]["id"] == "fallback-clarify"


def test_plan_invalid_suggested_tool_returns_fallback(planner_agent):
    """suggested_tool not in tool_index should trigger fallback."""
    bad_plan = [{
        "id": "t1",
        "description": "Use unknown tool",
        "intent": "retrieve",
        "suggested_tool": "nonexistent_tool",
    }]
    result = _call_plan(planner_agent, llm_content=json.dumps(bad_plan))

    assert result[0]["id"] == "fallback-clarify"


def test_plan_empty_context_uses_placeholder(planner_agent):
    """Empty context should still work; user prompt uses placeholder text."""
    valid_plan = [{"id": "t1", "description": "Search docs", "intent": "retrieve"}]
    mock_llm = _mock_llm(json.dumps(valid_plan))
    original_llm = planner_agent._llm
    planner_agent._llm = mock_llm
    try:
        result = planner_agent.plan(
            query="What is TOPMOST?",
            context="",
            tool_index=TOOL_INDEX,
            routing_hint="",
        )
    finally:
        planner_agent._llm = original_llm

    assert result == valid_plan
    user_msg = mock_llm.chat.call_args[0][0][1].content
    assert "（无）" in user_msg


def test_plan_non_list_json_returns_fallback(planner_agent):
    """JSON object (not array) should trigger fallback."""
    result = _call_plan(planner_agent, llm_content='{"id": "t1", "description": "x", "intent": "y"}')

    assert result[0]["id"] == "fallback-clarify"
