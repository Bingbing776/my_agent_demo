"""Stage 5.9 - MemoryManager.promote_to_long_term. See docs/test_outline.md"""
from datetime import datetime
from unittest.mock import MagicMock
import pytest

from test.helpers.samples import sample_mcp_tool_call_result

pytestmark = [pytest.mark.unit]


def test_promote(memory_manager):
    """promote_to_long_term moves qualifying items to long-term collection
    and removes them from short-term, while non-qualifying items remain.

    Uses sample_mcp_tool_call_result for realistic result shape with citations.
    Default config: threshold=0.7, w_time=0.3, w_importance=0.5, w_freq=0.2.
    """
    mock_lt = MagicMock()
    memory_manager._long_term_collection = mock_lt

    now = datetime.now()

    # Item that qualifies for promotion:
    #   score_time ~1.0 (recent), score_importance=0.95, score_freq=1-exp(-3)~0.95
    #   total = 0.3*1.0 + 0.5*0.95 + 0.2*0.95 = 0.965 >= 0.7
    qualifying = {
        "query": "What is TOPMOST?",
        "result": sample_mcp_tool_call_result(),
        "session_id": "s1",
        "timestamp": now,
        "score": 0.95,
        "access_count": 3,
        "embeddings": [],
    }

    # Item that does NOT qualify:
    #   score_time=0.0 (no timestamp), score_importance=0.1, score_freq=0.0
    #   total = 0.3*0.0 + 0.5*0.1 + 0.2*0.0 = 0.05 < 0.7
    non_qualifying = {
        "query": "some query",
        "result": {"text": "some result text"},
        "session_id": "s2",
        "score": 0.1,
        "access_count": 0,
        "embeddings": [],
    }

    memory_manager._short_term_memory = [qualifying, non_qualifying]

    memory_manager.promote_to_long_term()

    # Qualifying item must be removed from short-term
    assert qualifying not in memory_manager.short_term, (
        "qualifying item should be removed from short-term after promotion"
    )

    # Non-qualifying item must remain
    assert non_qualifying in memory_manager.short_term, (
        "non-qualifying item should remain in short-term"
    )

    # Long-term collection must have been written to
    assert mock_lt.add.called or mock_lt.upsert.called, (
        "long-term collection add/upsert should be called for qualifying items"
    )

    # Only one item should be in short-term after promotion
    assert len(memory_manager.short_term) == 1, (
        "exactly one non-qualifying item should remain in short-term"
    )
