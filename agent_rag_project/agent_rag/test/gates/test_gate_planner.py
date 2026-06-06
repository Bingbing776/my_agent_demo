"""Section 4 -- PlannerAgent function gate validation.

Test strategy:
- mock tests: use mock_llm to verify code logic (JSON parsing, validation, queue generation)
- @pytest.mark.llm_live tests: use real_llm to verify prompt quality
  confirm real LLM can return correct format subtask list per prompt requirements
"""
import json
import pytest
from unittest.mock import MagicMock

from agent_rag.agents.planner import PlannerAgent

pytestmark = [pytest.mark.gate]


# --- Mock tests (verify code logic) ---

TOOL_INDEX = (
    "- query_knowledge_hub: Search knowledge base for relevant chunks\n"
    "- read_chunk: Read a specific chunk by chunk_id\n"
    "- get_neighbor_chunks: Get surrounding chunks for context\n"
    "- check_evidence: Verify evidence sufficiency\n"
    "- search_by_metadata: Search by document metadata fields\n"
    "- get_document_full_text: Retrieve full document text\n"
    "- list_collections: List available collections\n"
    "- list_documents: List documents in a collection\n"
    "- get_document_summary: Get document summary\n"
    "- get_document_outline: Get document outline\n"
)

AVAILABLE_TOOLS = {
    "query_knowledge_hub", "read_chunk", "get_neighbor_chunks",
    "check_evidence", "search_by_metadata", "get_document_full_text",
    "list_collections", "list_documents", "get_document_summary",
    "get_document_outline",
}


def _mock_llm(content: str):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = content
    mock_llm.chat.return_value = mock_response
    return mock_llm


def test_planner_init(planner_agent):
    """Verify PlannerAgent constructs with all required internal state."""
    assert planner_agent is not None

    # config stored as dict (default {} when None passed)
    assert hasattr(planner_agent, '_config')
    assert isinstance(planner_agent._config, dict)

    # LLM created and cached during __init__
    assert hasattr(planner_agent, '_llm')
    assert planner_agent._llm is not None

    # routing skill path attribute must exist
    assert hasattr(planner_agent, '_routing_skill_path')

    # routing hint cache initialized to None
    assert hasattr(planner_agent, '_routing_hint_cache')
    assert planner_agent._routing_hint_cache is None


def test_planner_plan_returns_list(planner_agent):
    """Verify plan() returns subtask list for real queries.

    Each subtask must have id, description, intent.
    suggested_tool must be in available tools if present.
    Invalid items trigger fallback plan.
    """
    valid_plan = [
        {
            "id": "t1",
            "description": "Search knowledge hub for TOPMOST topic modeling features",
            "intent": "retrieve",
            "suggested_tool": "query_knowledge_hub",
            "done_criteria": "At least 3 relevant chunks found",
            "replan_triggers": "No results or empty results",
        },
        {
            "id": "t2",
            "description": "Read most relevant chunk for detailed evidence",
            "intent": "read",
            "suggested_tool": "read_chunk",
            "done_criteria": "Chunk content successfully retrieved",
            "replan_triggers": "Chunk not found or access error",
        },
        {
            "id": "t3",
            "description": "Get neighbor chunks for context completeness",
            "intent": "expand",
            "suggested_tool": "get_neighbor_chunks",
            "done_criteria": "Surrounding chunks retrieved",
        },
    ]

    mock_llm = _mock_llm(json.dumps(valid_plan))
    original_llm = planner_agent._llm
    planner_agent._llm = mock_llm
    try:
        result = planner_agent.plan(
            query="What is TOPMOST?",
            context="Prior conversation about TOPMOST",
            tool_index=TOOL_INDEX,
            routing_hint="Use query_knowledge_hub for initial retrieval",
        )
    finally:
        planner_agent._llm = original_llm

    # Must return a list
    assert isinstance(result, list), f"plan() must return list, got {type(result)}"
    assert len(result) >= 1, "plan() must return at least one subtask"

    for item in result:
        assert isinstance(item, dict), f"each plan item must be dict, got {type(item)}"
        assert "id" in item, "each item must have 'id'"
        assert "description" in item, "each item must have 'description'"
        assert "intent" in item, "each item must have 'intent'"

        if "suggested_tool" in item and item["suggested_tool"]:
            assert item["suggested_tool"] in AVAILABLE_TOOLS, (
                f"suggested_tool '{item['suggested_tool']}' not in available tools"
            )

        if "done_criteria" in item:
            assert isinstance(item["done_criteria"], str)
        if "replan_triggers" in item:
            assert isinstance(item["replan_triggers"], str)

    # Verify LLM was called with user prompt containing query/context/tool_index/routing_hint
    mock_llm.chat.assert_called_once()
    messages = mock_llm.chat.call_args[0][0]
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    user_content = messages[1].content
    assert "What is TOPMOST?" in user_content
    assert "Prior conversation about TOPMOST" in user_content
    assert "query_knowledge_hub" in user_content

    # Verify exact match with mock output
    assert result[0]["id"] == "t1"
    assert result[0]["suggested_tool"] == "query_knowledge_hub"
    assert result[0]["done_criteria"] == "At least 3 relevant chunks found"
    assert result[1]["id"] == "t2"
    assert result[1]["suggested_tool"] == "read_chunk"
    assert result[2]["id"] == "t3"


def test_planner_replan_returns_list(planner_agent):
    """Verify replan() returns corrected task list on retrieval failure observation.

    Observation must be passed into the LLM user prompt.
    Result items must have id, description, intent.
    retrieval_hints must not contain forbidden keywords (MQE, HyDE).
    """
    observation = (
        "task=t1 status=fail needs_replan=true issue=no_results_found "
        "The query_knowledge_hub returned zero chunks for the original query."
    )

    replan_output = [
        {
            "id": "r1",
            "description": "Retry search with broader English terms and keyword expansion",
            "intent": "retrieve",
            "suggested_tool": "query_knowledge_hub",
            "done_criteria": "At least 3 relevant chunks found",
            "replan_triggers": "No results returned after retry",
            "retrieval_hints": [
                "use broader English keywords",
                "try synonym expansion",
            ],
        },
        {
            "id": "r2",
            "description": "Search by metadata with narrower document filter",
            "intent": "retrieve",
            "suggested_tool": "search_by_metadata",
            "done_criteria": "At least one matching document found",
            "replan_triggers": "Filter too narrow, no results",
        },
    ]

    mock_llm = _mock_llm(json.dumps(replan_output))
    original_llm = planner_agent._llm
    planner_agent._llm = mock_llm
    try:
        result = planner_agent.replan(
            query="What is TOPMOST?",
            context="Previous retrieval failed",
            tool_index=TOOL_INDEX,
            routing_hint="Use query_knowledge_hub for retrieval",
            observation=observation,
        )
    finally:
        planner_agent._llm = original_llm

    assert isinstance(result, list), f"replan() must return list, got {type(result)}"
    assert len(result) >= 1, "replan() must return at least one subtask"

    for item in result:
        assert isinstance(item, dict)
        assert "id" in item
        assert "description" in item
        assert "intent" in item

        if "suggested_tool" in item and item["suggested_tool"]:
            assert item["suggested_tool"] in AVAILABLE_TOOLS, (
                f"suggested_tool '{item['suggested_tool']}' not in available tools"
            )

        if "retrieval_hints" in item:
            assert isinstance(item["retrieval_hints"], list)
            for hint in item["retrieval_hints"]:
                assert isinstance(hint, str)
                lower = hint.lower()
                assert "mqe" not in lower, (
                    "retrieval hints must not contain forbidden MQE reference"
                )
                assert "hyde" not in lower, (
                    "retrieval hints must not contain forbidden HyDE reference"
                )

    # Verify LLM was invoked with observation in user prompt
    mock_llm.chat.assert_called_once()
    messages = mock_llm.chat.call_args[0][0]
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    user_content = messages[1].content
    assert observation in user_content, (
        "observation must be passed into the LLM user prompt"
    )

    # Verify system prompt contains replan guidance
    system_content = messages[0].content
    assert "replan" in system_content.lower(), (
        "system prompt should contain replan strategy guidance"
    )

    # Verify first result matches mock output
    assert result[0]["id"] == "r1"
    assert result[0]["suggested_tool"] == "query_knowledge_hub"
    assert "retrieval_hints" in result[0]
    assert "use broader English keywords" in result[0]["retrieval_hints"]
    assert result[1]["id"] == "r2"
    assert result[1]["suggested_tool"] == "search_by_metadata"


# --- Real API tests (verify prompt quality) ---

@pytest.mark.llm_live
def test_real_planner_plan_prompt(real_llm, config):
    """Use real LLM to verify plan() prompt produces correctly formatted subtask list.

    Validates:
    - LLM returns a JSON array
    - Each item has id, description, intent
    - suggested_tool is within available tools
    """
    from agent_rag.agents.planner import PlannerAgent

    rag_cfg = config.get("rag_agent", {}) if isinstance(config, dict) else {}
    planner = PlannerAgent(config=rag_cfg)
    planner._llm = real_llm

    result = planner.plan(
        query="What are the key features of TOPMOST?",
        context="Prior discussion about topic modeling toolkits",
        tool_index=TOOL_INDEX,
        routing_hint=(
            "Use query_knowledge_hub for initial retrieval; "
            "fallback to search_by_metadata"
        ),
    )

    assert isinstance(result, list), f"plan() must return list, got {type(result)}"
    assert len(result) >= 1, "plan() must return at least one subtask"

    for item in result:
        assert isinstance(item, dict), f"each plan item must be dict, got {type(item)}"
        assert "id" in item, "each item must have 'id'"
        assert "description" in item, "each item must have 'description'"
        assert "intent" in item, "each item must have 'intent'"

        if "suggested_tool" in item and item["suggested_tool"]:
            assert item["suggested_tool"] in AVAILABLE_TOOLS, (
                f"suggested_tool '{item['suggested_tool']}' not in available tools"
            )


@pytest.mark.llm_live
def test_real_planner_replan_prompt(real_llm, config):
    """Use real LLM to verify replan() prompt produces correctly formatted revised tasks."""
    from agent_rag.agents.planner import PlannerAgent

    rag_cfg = config.get("rag_agent", {}) if isinstance(config, dict) else {}
    planner = PlannerAgent(config=rag_cfg)
    planner._llm = real_llm

    observation = (
        "task=t1 status=fail needs_replan=true issue=no_results_found\n"
        "The query_knowledge_hub returned zero chunks. "
        "The search query may be too narrow."
    )

    result = planner.replan(
        query="How does TOPMOST compare with OCTIS?",
        context="Initial retrieval attempt returned no results",
        tool_index=TOOL_INDEX,
        routing_hint=(
            "Use query_knowledge_hub for retrieval; "
            "try search_by_metadata as fallback"
        ),
        observation=observation,
    )

    assert isinstance(result, list), f"replan() must return list, got {type(result)}"
    assert len(result) >= 1, "replan() must return at least one subtask"

    for item in result:
        assert isinstance(item, dict)
        assert "id" in item
        assert "description" in item
        assert "intent" in item

        if "suggested_tool" in item and item["suggested_tool"]:
            assert item["suggested_tool"] in AVAILABLE_TOOLS, (
                f"suggested_tool '{item['suggested_tool']}' not in available tools"
            )

        if "retrieval_hints" in item:
            assert isinstance(item["retrieval_hints"], list)
            for hint in item["retrieval_hints"]:
                assert isinstance(hint, str)
                lower = hint.lower()
                assert "mqe" not in lower
                assert "hyde" not in lower
