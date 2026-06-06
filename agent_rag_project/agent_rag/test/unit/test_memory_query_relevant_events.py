"""Stage 5.13 - MemoryManager.query_relevant_events. See docs/test_outline.md"""
import pytest
import sqlite3
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]


def test_session_filter(memory_manager):
    """query_relevant_events filters episodic events by session_id via Qdrant filter."""
    # Setup in-memory SQLite with episodic_events for two different sessions
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE episodic_events (
            event_id TEXT PRIMARY KEY,
            event_text TEXT,
            timestamp TEXT,
            session_id TEXT,
            related_chunks TEXT
        )
        """
    )

    sid_a = "session-aaa-111"
    sid_b = "session-bbb-222"

    conn.execute(
        "INSERT INTO episodic_events VALUES (?,?,?,?,?)",
        ("e1", "Event A1: TOPMOST architecture overview", "2024-06-01T10:00:00", sid_a, "[]"),
    )
    conn.execute(
        "INSERT INTO episodic_events VALUES (?,?,?,?,?)",
        ("e2", "Event A2: OCTIS comparison analysis", "2024-06-01T11:00:00", sid_a, "[]"),
    )
    conn.execute(
        "INSERT INTO episodic_events VALUES (?,?,?,?,?)",
        ("e3", "Event B1: MAGE detection challenges", "2024-06-02T09:00:00", sid_b, "[]"),
    )
    conn.commit()

    memory_manager.sqlite_conn = conn

    # Mock Qdrant: search returns only session A events (Qdrant already filtered)
    mock_qdrant = MagicMock()
    pt1 = MagicMock()
    pt1.id = "e1"
    pt1.payload = {"event_id": "e1", "session_id": sid_a, "timestamp": "2024-06-01T10:00:00"}
    pt2 = MagicMock()
    pt2.id = "e2"
    pt2.payload = {"event_id": "e2", "session_id": sid_a, "timestamp": "2024-06-01T11:00:00"}
    mock_qdrant.search.return_value = [pt1, pt2]
    memory_manager.qdrant_collection = mock_qdrant

    result = memory_manager.query_relevant_events("topic modeling architecture", sid_a)

    # Must return a non-empty string
    assert isinstance(result, str)
    assert len(result) > 0, "query_relevant_events must return non-empty result for matching events"

    # Must contain session A events
    assert "Event A1" in result
    assert "Event A2" in result

    # Must NOT contain session B events (Qdrant filter excludes them)
    assert "Event B1" not in result

    # Verify Qdrant search was called with the correct session_id filter
    mock_qdrant.search.assert_called_once()
    call_kwargs = mock_qdrant.search.call_args.kwargs
    query_filter = call_kwargs.get("query_filter")
    assert query_filter is not None, "query_filter must be passed to Qdrant search"

    # The filter (dict or qdrant_client Filter) must include session_id constraint
    if isinstance(query_filter, dict):
        must_clauses = query_filter.get("must", [])
        session_clauses = [c for c in must_clauses if c.get("key") == "session_id"]
        assert len(session_clauses) == 1, (
            "query_filter must contain exactly one session_id clause"
        )
        assert session_clauses[0]["match"]["value"] == sid_a, (
            "query_filter session_id must match the requested session"
        )

    conn.close()
