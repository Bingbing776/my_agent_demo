"""ContextManager.update_context tests"""
import pytest

pytestmark = [pytest.mark.unit]

def test_appends(context_manager):
    """update_context appends items with correct keys, auto-generates session_id, and respects max_entries."""
    # Basic append with explicit session_id
    context_manager.update_context("hello", "world", session_id="s1")
    assert len(context_manager.context_window) == 1
    item = context_manager.context_window[0]
    assert item["query"] == "hello"
    assert item["answer"] == "world"
    assert item["session_id"] == "s1"
    assert "timestamp" in item

    # Second append preserves order
    context_manager.update_context("q2", "a2", session_id="s2")
    assert len(context_manager.context_window) == 2
    assert context_manager.context_window[0]["query"] == "hello"
    assert context_manager.context_window[1]["query"] == "q2"

    # Auto-generated session_id when not provided
    cm = type(context_manager)(config=context_manager.config)
    cm.update_context("auto", "answer")
    assert len(cm.context_window) == 1
    assert cm.context_window[0]["query"] == "auto"
    assert cm.context_window[0]["answer"] == "answer"
    sid = cm.context_window[0]["session_id"]
    assert isinstance(sid, str)
    assert len(sid) > 0

    # max_entries truncation: oldest evicted when exceeding limit
    cm2 = type(context_manager)(config={"max_entries": 2})
    cm2.update_context("q1", "a1")
    cm2.update_context("q2", "a2")
    cm2.update_context("q3", "a3")
    assert len(cm2.context_window) == 2
    assert cm2.context_window[0]["query"] == "q2"
    assert cm2.context_window[1]["query"] == "q3"
