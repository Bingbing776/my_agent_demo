"""Unit tests for ContextManager.get_context_window."""
import pytest

pytestmark = [pytest.mark.unit]


def test_recent_n(context_manager):
    """Test get_context_window: returns at most n items, sorted by timestamp desc,
    supports session filtering, and does not modify original list."""
    import time

    # Setup: add items with different sessions and timestamps
    context_manager.update_context("q1", "a1", session_id="sess_a")
    time.sleep(0.02)
    context_manager.update_context("q2", "a2", session_id="sess_b")
    time.sleep(0.02)
    context_manager.update_context("q3", "a3", session_id="sess_a")

    # 1. Returns at most n items
    w = context_manager.get_context_window(2)
    assert len(w) == 2, f"expected 2, got {len(w)}"

    # 2. Each item is a dict with required keys
    for item in w:
        assert isinstance(item, dict)
        for key in ("query", "answer", "session_id", "timestamp"):
            assert key in item, f"missing key: {key}"

    # 3. Sorted by timestamp descending (newest first: q3, q2)
    assert w[0]["query"] == "q3", "newest item should be first"
    assert w[1]["query"] == "q2"

    # 4. Session filtering: only items from specified session
    w_a = context_manager.get_context_window(10, session_id="sess_a")
    assert len(w_a) == 2, f"expected 2 for sess_a, got {len(w_a)}"
    assert all(it["session_id"] == "sess_a" for it in w_a)
    # within session: newest first
    assert w_a[0]["query"] == "q3"
    assert w_a[1]["query"] == "q1"

    # 5. Single item for sess_b
    w_b = context_manager.get_context_window(10, session_id="sess_b")
    assert len(w_b) == 1
    assert w_b[0]["query"] == "q2"
    assert w_b[0]["session_id"] == "sess_b"

    # 6. Non-existent session returns empty list
    w_none = context_manager.get_context_window(10, session_id="nonexist")
    assert w_none == []

    # 7. Does not modify original list
    original_len = len(context_manager.context_window)
    context_manager.get_context_window(1)
    assert len(context_manager.context_window) == original_len
    assert context_manager.context_window[0]["query"] == "q1"

    # 8. n=0 edge case
    w0 = context_manager.get_context_window(0)
    assert w0 == []

    # 9. n larger than available returns all
    w_all = context_manager.get_context_window(100)
    assert len(w_all) == 3

    # 10. Default (no session_id) returns items from all sessions
    sessions = {it["session_id"] for it in w_all}
    assert sessions == {"sess_a", "sess_b"}
