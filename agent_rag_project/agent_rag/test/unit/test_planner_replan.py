"""Phase 3.3 - PlannerAgent.replan. See docs/test_outline.md"""
import pytest
from unittest.mock import MagicMock

from agent_rag.agents.planner import PlannerAgent

pytestmark = [pytest.mark.unit]


def test_includes_observation(planner_agent):
    """Verify replan passes observation into the LLM user prompt and returns valid plan items."""
    # Replace internally-created LLM with a mock to capture messages
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        '[{"id": "r1", "description": "retry search with broader terms", '
        '"intent": "retrieve", "suggested_tool": "query_knowledge_hub", '
        '"done_criteria": "at least 3 relevant chunks found", '
        '"replan_triggers": "no results returned", '
        '"retrieval_hints": ["use broader English keywords", "try synonym expansion"]}]'
    )
    mock_llm.chat.return_value = mock_response
    planner_agent._llm = mock_llm

    observation = "task=t1 status=fail needs_replan=true issue=no_results_found"
    tool_index = (
        "- query_knowledge_hub: search the knowledge base for relevant chunks\n"
        "- read_chunk: read a specific chunk by chunk_id\n"
        "- get_document_full_text: retrieve full document text\n"
        "- search_by_metadata: search by document metadata fields"
    )

    query = "What is TOPMOST?"
    context = "No prior context available"
    routing_hint = "Use query_knowledge_hub for initial retrieval"

    result = planner_agent.replan(
        query=query,
        context=context,
        tool_index=tool_index,
        routing_hint=routing_hint,
        observation=observation,
    )

    # Assert LLM was invoked exactly once
    mock_llm.chat.assert_called_once()

    # Assert LLM was called with two messages (system + user)
    messages = mock_llm.chat.call_args[0][0]
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"

    user_prompt = messages[1].content

    # Assert observation text appears in the user prompt
    assert observation in user_prompt, (
        "observation must be passed into the LLM user prompt"
    )

    # Assert query appears in the user prompt
    assert query in user_prompt, (
        "query must be passed into the LLM user prompt"
    )

    # Assert context appears in the user prompt
    assert context in user_prompt, (
        "context must be passed into the LLM user prompt"
    )

    # Assert routing_hint appears in the user prompt
    assert routing_hint in user_prompt, (
        "routing_hint must be passed into the LLM user prompt"
    )

    # Assert the system prompt contains replan guidance keywords
    assert "replan" in messages[0].content.lower(), (
        "system prompt should contain replan strategy guidance"
    )

    # Assert result is a list of dicts with required keys
    assert isinstance(result, list), "replan must return a list"
    assert len(result) >= 1, "replan must return at least one item"

    for item in result:
        assert isinstance(item, dict), "each plan item must be a dict"
        assert "id" in item, "each item must have 'id'"
        assert "description" in item, "each item must have 'description'"
        assert "intent" in item, "each item must have 'intent'"

        # suggested_tool must match an available tool if present
        if "suggested_tool" in item and item["suggested_tool"]:
            assert item["suggested_tool"] in {
                "query_knowledge_hub",
                "read_chunk",
                "get_document_full_text",
                "search_by_metadata",
            }, f"suggested_tool '{item['suggested_tool']}' not in available tools"

        # Optional keys that were in the LLM output must be preserved
        if "done_criteria" in item:
            assert isinstance(item["done_criteria"], str), (
                "done_criteria must be a string"
            )
        if "replan_triggers" in item:
            assert isinstance(item["replan_triggers"], str), (
                "replan_triggers must be a string"
            )
        if "retrieval_hints" in item:
            assert isinstance(item["retrieval_hints"], list), (
                "retrieval_hints must be a list"
            )
            for hint in item["retrieval_hints"]:
                assert isinstance(hint, str), "each retrieval hint must be a string"
                lower = hint.lower()
                assert "mqe" not in lower, (
                    "retrieval hints must not contain forbidden MQE reference"
                )
                assert "hyde" not in lower, (
                    "retrieval hints must not contain forbidden HyDE reference"
                )

    # Verify the first result item matches the mock LLM output exactly
    first = result[0]
    assert first["id"] == "r1"
    assert first["description"] == "retry search with broader terms"
    assert first["intent"] == "retrieve"
    assert first["suggested_tool"] == "query_knowledge_hub"
    assert first["done_criteria"] == "at least 3 relevant chunks found"
    assert first["replan_triggers"] == "no results returned"
    assert "retrieval_hints" in first
    assert "use broader English keywords" in first["retrieval_hints"]
    assert "try synonym expansion" in first["retrieval_hints"]
