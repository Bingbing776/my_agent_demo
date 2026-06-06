"""Section 2 - ContextManager gate acceptance tests."""
import pytest

from agent_rag.context.context_manager import ContextManager

pytestmark = [pytest.mark.gate]


def test_empty_window_on_init(context_manager):
    """Verify context_window is empty list on initialization."""
    assert isinstance(context_manager.context_window, list)
    assert context_manager.context_window == []
    assert len(context_manager.context_window) == 0


def test_update_and_get_window(context_manager):
    """Verify multi-turn conversation update and window retrieval using sample_memory_conversation."""
    from test.helpers.samples import sample_memory_conversation

    conversation = sample_memory_conversation()
    session_id = "gate-context-session-1"

    # Pair user/assistant messages from sample_memory_conversation
    turns = [
        (conversation[0]["content"], conversation[1]["content"]),
        (conversation[2]["content"], conversation[3]["content"]),
    ]

    for query, answer in turns:
        context_manager.update_context(query, answer, session_id=session_id)

    # Verify context_window populated
    assert len(context_manager.context_window) == 2

    # get_context_window returns items with required keys
    window = context_manager.get_context_window(5)
    assert len(window) == 2
    for item in window:
        assert "query" in item
        assert "answer" in item
        assert "session_id" in item
        assert "timestamp" in item
        assert item["session_id"] == session_id

    # Session filter works
    window_filtered = context_manager.get_context_window(5, session_id=session_id)
    assert len(window_filtered) == 2
    window_none = context_manager.get_context_window(5, session_id="nonexistent")
    assert len(window_none) == 0

    # n parameter respected
    window_n1 = context_manager.get_context_window(1)
    assert len(window_n1) == 1

    # Sorted by timestamp descending: most recent first
    assert window[0]["query"] == turns[-1][0]

    # get_context_window does not mutate original list
    original_len = len(context_manager.context_window)
    _ = context_manager.get_context_window(1)
    assert len(context_manager.context_window) == original_len


def test_get_relevant_context(context_manager):
    """Verify get_relevant_context returns compressed context string for matching content."""
    from test.helpers.samples import sample_memory_conversation

    conversation = sample_memory_conversation()
    session_id = "gate-context-session-2"

    turns = [
        (conversation[0]["content"], conversation[1]["content"]),
        (conversation[2]["content"], conversation[3]["content"]),
    ]
    for query, answer in turns:
        context_manager.update_context(query, answer, session_id=session_id)

    # get_relevant_context returns non-empty string when context has relevant data
    result = context_manager.get_relevant_context("TOPMOST")
    assert isinstance(result, str)
    assert len(result) > 0, (
        "get_relevant_context must return non-empty string "
        "when context window contains relevant data"
    )

    # Session filter works with get_relevant_context
    result_filtered = context_manager.get_relevant_context(
        "TOPMOST", session_id=session_id
    )
    assert isinstance(result_filtered, str)
    assert len(result_filtered) > 0

    # Non-matching session returns empty when no candidates
    result_other = context_manager.get_relevant_context(
        "TOPMOST", session_id="nonexistent"
    )
    assert result_other == ""

    # Empty context window returns empty string
    cm_empty = ContextManager(config={})
    result_empty = cm_empty.get_relevant_context("any query")
    assert result_empty == ""
