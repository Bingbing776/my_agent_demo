"""Stage 5.12 - MemoryManager.add_event. See docs/test_outline.md"""
import pytest
import sqlite3
from unittest.mock import MagicMock
from datetime import datetime

pytestmark = [pytest.mark.unit]


def test_dual_write(memory_manager):
    """add_event writes to both SQLite and Qdrant (dual write)."""
    from test.helpers.samples import sample_mcp_tool_call_result

    # Attach mock connections to verify dual write
    sqlite_conn = sqlite3.connect(":memory:")
    mock_qdrant = MagicMock()

    memory_manager.sqlite_conn = sqlite_conn
    memory_manager.qdrant_collection = mock_qdrant

    memory_item = {
        "query": "What is TOPMOST?",
        "result": sample_mcp_tool_call_result(),
        "score": 0.85,
        "timestamp": datetime.now(),
        "session_id": "test-session-1",
    }

    memory_manager.add_event(memory_item)

    # Verify SQLite write: at least one row in episodic_events
    cursor = sqlite_conn.cursor()
    cursor.execute(
        "SELECT event_id, event_text, timestamp, session_id, related_chunks "
        "FROM episodic_events"
    )
    rows = cursor.fetchall()
    assert len(rows) >= 1, (
        "add_event must write at least one row to SQLite episodic_events"
    )

    event_id, event_text, ts, sid, chunks_json = rows[0]
    assert event_id, "event_id must not be empty"
    assert event_text, "event_text must not be empty"
    assert sid == "test-session-1", "session_id must match input"

    # Verify Qdrant write: upsert or add was called
    assert mock_qdrant.upsert.called or mock_qdrant.add.called, (
        "add_event must call upsert or add on qdrant_collection"
    )

    sqlite_conn.close()
