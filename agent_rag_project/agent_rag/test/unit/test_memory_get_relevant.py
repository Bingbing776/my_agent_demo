"""MemoryManager.get_relevant unit tests.\n\nSee docs/test_outline.md task 1.12.\n"""
import pytest

pytestmark = [pytest.mark.unit]


def test_top_k(memory_manager):
    """get_relevant must return at most top_k items sorted by score descending."""
    top_k = memory_manager.short_term_k + memory_manager.long_term_k

    # Add more items than top_k to short-term memory
    for i in range(top_k + 5):
        result = {
            "text": f"result text for memory item {i}",
            "citations": [
                {"text_snippet": f"citation snippet {i}", "chunk_id": f"chunk_{i}"}
            ]
        }
        memory_manager.add_short_term(f"query for item {i}", result)

    assert len(memory_manager.short_term) == top_k + 5

    relevant = memory_manager.get_relevant("some search query")

    # Must respect top_k limit
    assert len(relevant) <= top_k, f"expected <= {top_k}, got {len(relevant)}"

    # Each item must have text and score keys
    for item in relevant:
        assert "text" in item, f"item missing 'text': {item.keys()}"
        assert "score" in item, f"item missing 'score': {item.keys()}"
        assert isinstance(item["score"], (int, float))
        assert 0.0 <= item["score"] <= 1.0

    # Items must be sorted by score descending
    scores = [item["score"] for item in relevant]
    assert scores == sorted(scores, reverse=True), f"scores not sorted descending: {scores}"
