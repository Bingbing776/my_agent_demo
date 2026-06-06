"""§1 — MemoryManager gate acceptance tests."""
import pytest
from unittest.mock import MagicMock

from test.helpers.imports import import_class

pytestmark = [pytest.mark.gate]


def test_add_and_retrieve_short_term(memory_manager):
    """Verify short-term memory can be written and retrieved via get_relevant."""
    query = "What is TOPMOST?"
    result = {
        "text": "TOPMOST is a topic modeling toolkit.",
        "citations": [
            {"text_snippet": "TOPMOST reaches a wider coverage", "chunk_id": "c1"}
        ],
        "score": 0.95,
    }

    memory_manager.add_short_term(query, result, session_id="session-1")

    # Verify item is in short_term list
    assert len(memory_manager.short_term) >= 1
    item = memory_manager.short_term[0]
    assert item["query"] == query
    assert item["session_id"] == "session-1"
    assert "timestamp" in item
    assert "score" in item
    assert "access_count" in item
    assert item["access_count"] == 0

    # Retrieve via get_relevant
    relevant = memory_manager.get_relevant(query)
    assert isinstance(relevant, list)
    assert len(relevant) >= 1
    for r in relevant:
        assert "text" in r
        assert "score" in r
        assert isinstance(r["text"], str)
        assert isinstance(r["score"], float)
        assert 0.0 <= r["score"] <= 1.0


def test_multi_turn_memory(memory_manager):
    """Verify multi-turn conversation memory persists across turns."""
    turns = [
        (
            "What is TOPMOST?",
            {
                "text": "TOPMOST is a topic modeling toolkit.",
                "citations": [
                    {"text_snippet": "TOPMOST reaches wider coverage", "chunk_id": "c1"}
                ],
            },
        ),
        (
            "How does it compare to OCTIS?",
            {
                "text": "TOPMOST covers more scenarios than OCTIS.",
                "citations": [
                    {"text_snippet": "covers dynamic and cross-lingual", "chunk_id": "c2"}
                ],
            },
        ),
        (
            "What is the architecture?",
            {
                "text": "It has modular design.",
                "citations": [
                    {"text_snippet": "decoupled dataset handler", "chunk_id": "c3"}
                ],
            },
        ),
    ]

    for query, result in turns:
        memory_manager.add_short_term(query, result, session_id="multi-turn")

    # All three turns should be in memory
    assert len(memory_manager.short_term) == 3

    # Verify items have distinct queries
    queries = {item["query"] for item in memory_manager.short_term}
    assert len(queries) == 3

    # First turn query should retrieve relevant content
    relevant = memory_manager.get_relevant("TOPMOST")
    assert len(relevant) >= 1

    # Third turn query should retrieve architecture-related content
    relevant = memory_manager.get_relevant("architecture")
    assert len(relevant) >= 1


def test_add_event_stores(memory_manager):
    """Verify event memory can be written when sqlite_conn is provided."""
    MemoryManager = import_class("MemoryManager")

    mock_conn = MagicMock()
    mm = MemoryManager(
        long_term_collection=None,
        sqlite_conn=mock_conn,
        qdrant_collection=None,
        config={},
    )

    event = {
        "query": "test query",
        "result": {
            "text": "test result text",
            "citations": [{"text_snippet": "evidence text", "chunk_id": "chunk-1"}],
        },
        "session_id": "event-session",
        "score": 0.8,
    }

    mm.add_event(event)

    # Verify sqlite interactions: CREATE TABLE + INSERT
    assert mock_conn.execute.call_count >= 2, (
        "add_event must call execute at least for CREATE TABLE and INSERT"
    )
    mock_conn.commit.assert_called()

    # Also verify default fixture does not crash with None connections
    memory_manager.add_event({"query": "q", "result": {"text": "t"}})


def test_retrieve_context_returns_str(memory_manager):
    """Verify retrieve_context returns a non-empty string summary."""
    # Empty/None query must return empty string
    assert memory_manager.retrieve_context("") == ""
    assert memory_manager.retrieve_context(None) == ""

    # Empty memory must return empty string
    ctx = memory_manager.retrieve_context("q")
    assert isinstance(ctx, str)
    assert ctx == ""

    # Populate with realistic data
    from test.helpers.samples import sample_mcp_tool_call_result
    result = sample_mcp_tool_call_result()
    memory_manager.add_short_term("TOPMOST features", result)

    ctx2 = memory_manager.retrieve_context("TOPMOST")
    assert isinstance(ctx2, str)
    assert len(ctx2) > 0, (
        "retrieve_context with populated memory must return non-empty string"
    )
