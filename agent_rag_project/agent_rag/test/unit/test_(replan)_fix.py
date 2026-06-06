"""Stage 4 -- PlannerAgent.replan fix test (replaces old test_planner_replan.py skip placeholder).

Validates replan per tech_doc §4:
- Returns list[dict] (same shape as plan), each with id/description/intent
- user_prompt section 5 includes observation
- Output does not contain inputSchema field
- observation is truncated when too long
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from test.helpers.imports import import_class
from test.helpers.samples import sample_subtask_plan


def _build_planner_with_llm(mock_llm: MagicMock, config: dict | None = None):
    """Build PlannerAgent and inject mock LLM.

    Bypasses conftest planner_agent fixture which may skip due to __init__
    not being implemented. If PlannerAgent itself cannot be instantiated, skip.
    """
    cls = import_class("PlannerAgent")
    for kwargs in (
        {},
        {"config": config or {}},
        {"config": (config or {}).get("rag_agent", {})},
    ):
        try:
            instance = cls(**kwargs)
            break
        except TypeError:
            continue
    else:
        pytest.skip("PlannerAgent.__init__ not implemented")

    if hasattr(instance, "_llm"):
        instance._llm = mock_llm
    else:
        instance._llm = mock_llm
    return instance


def test_replan_method_exists_on_planner():
    """PlannerAgent instance must have a replan method."""
    cls = import_class("PlannerAgent")
    instance = cls() if cls else None
    if instance is None:
        pytest.skip("PlannerAgent class not importable")
    assert hasattr(instance, "replan"), (
        "PlannerAgent must have a 'replan' method per tech_doc §4"
    )


def test_replan_returns_list_of_dicts(config, mock_llm):
    """replan must return list[dict] (same shape as plan output)."""
    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    mock_llm.chat.return_value = json.dumps([
        {"id": "r1", "description": "supplement metadata lookup", "intent": "search_metadata"},
    ])

    result = planner.replan(
        query="What is TOPMOST?",
        context="previous context summary",
        tool_index="- query_knowledge_hub: search documents",
        routing_hint="use query_knowledge_hub for retrieval",
        observation="subtask t0 returned empty results, need to broaden search terms",
    )

    assert isinstance(result, list), f"expected list, got {type(result).__name__}"
    assert len(result) >= 1, "replan should return at least one subtask"
    for item in result:
        assert isinstance(item, dict), f"each item must be dict, got {type(item).__name__}: {item}"


def test_replan_items_have_required_keys(config, mock_llm):
    """Each replan item must contain id, description, intent (tech_doc §4 plan required keys)."""
    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    expected = [
        {"id": "r1", "description": "supplement metadata lookup", "intent": "search_metadata"},
        {
            "id": "r2",
            "description": "read full text for complete evidence",
            "intent": "read_full_text",
            "suggested_tool": "get_document_full_text",
            "done_criteria": "obtained complete document body",
            "replan_triggers": "full text still missing key paragraphs",
        },
    ]
    mock_llm.chat.return_value = json.dumps(expected)

    result = planner.replan(
        query="compare TOPMOST and OCTIS",
        context="",
        tool_index=(
            "- query_knowledge_hub: search\n"
            "- get_document_full_text: read full doc"
        ),
        routing_hint="",
        observation="missing comparison data, only retrieved TOPMOST single paper",
    )

    assert len(result) == 2
    for item in result:
        assert "id" in item, f"missing 'id' in {item}"
        assert "description" in item, f"missing 'description' in {item}"
        assert "intent" in item, f"missing 'intent' in {item}"
        assert isinstance(item["id"], (str, int)), f"id must be str/int, got {type(item['id']).__name__}"
        assert isinstance(item["description"], str), f"description must be str"
        assert isinstance(item["intent"], str), f"intent must be str"


def test_includes_observation_in_user_prompt(config):
    """replan must pass observation into user_prompt section 5 (tech_doc §4 step 1)."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps([
        {"id": "t1", "description": "retry with new keywords", "intent": "retrieve"}
    ])

    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    observation = (
        "subtask t0: query_knowledge_hub returned empty results 3 times consecutively, "
        "switch to search_by_metadata for document ID lookup"
    )
    planner.replan(
        query="How does UMC handle multimodal utterances?",
        context="UMC is a clustering approach",
        tool_index=(
            "- query_knowledge_hub: semantic search\n"
            "- search_by_metadata: filter by doc_id"
        ),
        routing_hint="prefer search_by_metadata for targeted lookups",
        observation=observation,
    )

    assert mock_llm.chat.called, "replan must call self._llm.chat()"
    all_call_text = json.dumps(
        [str(a) for a in mock_llm.chat.call_args[0]],
        ensure_ascii=False,
    ) + json.dumps(
        {k: str(v) for k, v in (mock_llm.chat.call_args[1] if len(mock_llm.chat.call_args) > 1 else {}).items()},
        ensure_ascii=False,
    )
    assert observation in all_call_text, (
        f"observation must appear in the prompt sent to LLM.\n"
        f"Observation: {observation[:100]}...\n"
        f"Chat args preview: {all_call_text[:500]}"
    )


def test_output_does_not_contain_input_schema(config, mock_llm):
    """replan output must not contain inputSchema (MCP inputSchema managed by Executor, not Planner)."""
    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    mock_llm.chat.return_value = json.dumps([
        {"id": "t1", "description": "search with new query", "intent": "retrieve", "suggested_tool": "query_knowledge_hub"}
    ])

    result = planner.replan(
        query="test query",
        context="",
        tool_index="- query_knowledge_hub: search",
        routing_hint="",
        observation="need more evidence",
    )

    result_json = json.dumps(result, ensure_ascii=False)
    assert "inputSchema" not in result_json, (
        f"output must not contain inputSchema. Found in: {result_json[:300]}"
    )


def test_truncates_long_observation(config, mock_llm):
    """Long observation should be truncated to prevent prompt overflow (tech_doc §4 + test_outline §3.3)."""
    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    mock_llm.chat.return_value = json.dumps([
        {"id": "t1", "description": "retry", "intent": "retrieve"}
    ])

    long_obs = "x" * 20000
    planner.replan(
        query="test",
        context="",
        tool_index="- t: d",
        routing_hint="",
        observation=long_obs,
    )

    assert mock_llm.chat.called
    all_call_text = json.dumps(
        [str(a) for a in mock_llm.chat.call_args[0]],
        ensure_ascii=False,
    ) + json.dumps(
        {k: str(v) for k, v in (mock_llm.chat.call_args[1] if len(mock_llm.chat.call_args) > 1 else {}).items()},
        ensure_ascii=False,
    )
    assert long_obs not in all_call_text, (
        "long observation should be truncated before being sent to LLM; "
        "full 20000-char observation must not appear verbatim in prompt"
    )


def test_empty_observation_does_not_crash(config, mock_llm):
    """Empty observation should not crash replan."""
    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    mock_llm.chat.return_value = json.dumps([
        {"id": "t1", "description": "fresh start", "intent": "retrieve"}
    ])

    result = planner.replan(
        query="test query",
        context="",
        tool_index="- query_knowledge_hub: search",
        routing_hint="",
        observation="",
    )

    assert isinstance(result, list)
    assert len(result) >= 1
    assert "id" in result[0]


def test_replan_with_realistic_subtask_data(config, mock_llm):
    """Use sample_subtask_plan real business data to construct observation and validate replan."""
    planner = _build_planner_with_llm(mock_llm, config)
    if not hasattr(planner, "replan"):
        pytest.skip("replan not implemented")

    plan_tasks = sample_subtask_plan()
    assert len(plan_tasks) >= 2, "sample_subtask_plan must have at least 2 tasks"

    tool_names = sorted({t["tool_name"] for t in plan_tasks if t.get("tool_name")})
    tool_index = "\n".join(f"- {n}: tool description" for n in tool_names)

    observation = (
        "subtask t1 (read_chunk) returned chunk content that does not match "
        "query_knowledge_hub retrieval results; chunk_id=9a08dfd1_0001_6c80634a "
        "does not exist in the knowledge base. "
        "Suggest switching to get_neighbor_chunks or search_by_metadata to locate correct chunk."
    )

    mock_llm.chat.return_value = json.dumps([
        {
            "id": "t1b",
            "description": "use query_knowledge_hub to re-search and locate correct document chunk",
            "intent": "retrieve",
            "suggested_tool": "query_knowledge_hub",
        },
        {
            "id": "t1c",
            "description": "read neighbor chunks to get complete context",
            "intent": "read_chunk",
            "suggested_tool": "read_chunk",
        },
    ])

    result = planner.replan(
        query="What core problem in existing topic modeling research does TOPMOST mainly solve?",
        context="TOPMOST is a topic modeling toolkit",
        tool_index=tool_index,
        routing_hint="use query_knowledge_hub for broad search, search_by_metadata for targeted lookups",
        observation=observation,
    )

    assert isinstance(result, list)
    assert len(result) >= 1
    for item in result:
        assert "id" in item
        assert "description" in item
        assert "intent" in item
        if item.get("suggested_tool"):
            assert item["suggested_tool"] in tool_names, (
                f"suggested_tool '{item['suggested_tool']}' not in available tools: {tool_names}"
            )
