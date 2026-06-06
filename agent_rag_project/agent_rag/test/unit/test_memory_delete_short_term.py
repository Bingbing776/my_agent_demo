"""Phase 5.8 - MemoryManager.delete_short_term. See docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]


def test_removes(memory_manager):
    """Verify delete_short_term removes specified items while keeping others,
    handles empty list as no-op, and safely ignores non-existent items."""

    # 1. Populate short_term with three distinct items
    memory_manager.add_short_term("q1", {"text": "answer one"}, session_id="s1")
    memory_manager.add_short_term("q2", {"text": "answer two"}, session_id="s2")
    memory_manager.add_short_term("q3", {"text": "answer three"}, session_id="s3")

    assert len(memory_manager.short_term) == 3

    # 2. Get references to the actual dict objects in short_term
    item_a = memory_manager.short_term[0]  # q1
    item_b = memory_manager.short_term[1]  # q2
    item_c = memory_manager.short_term[2]  # q3

    # 3. Delete the middle item (item_b)
    memory_manager.delete_short_term([item_b])

    # 4. Verify item_b is removed, item_a and item_c remain
    assert len(memory_manager.short_term) == 2
    assert item_b not in memory_manager.short_term
    assert item_a in memory_manager.short_term
    assert item_c in memory_manager.short_term

    # 5. Verify remaining items have correct queries
    remaining_queries = [item["query"] for item in memory_manager.short_term]
    assert "q1" in remaining_queries
    assert "q3" in remaining_queries
    assert "q2" not in remaining_queries

    # 6. Delete multiple items at once (item_a and item_c)
    memory_manager.delete_short_term([item_a, item_c])
    assert len(memory_manager.short_term) == 0


def test_delete_empty_list_noop(memory_manager):
    """delete_short_term with empty list should be a no-op."""
    memory_manager.add_short_term("q1", {"text": "a1"})
    memory_manager.add_short_term("q2", {"text": "a2"})

    assert len(memory_manager.short_term) == 2

    memory_manager.delete_short_term([])

    # Both items should remain
    assert len(memory_manager.short_term) == 2


def test_delete_non_existent_safe(memory_manager):
    """delete_short_term should not raise when to_delete contains items
    not in short_term."""
    memory_manager.add_short_term("q1", {"text": "a1"})
    memory_manager.add_short_term("q2", {"text": "a2"})

    fake_item = {"query": "ghost", "result": {}, "session_id": "x"}

    # Should not raise
    memory_manager.delete_short_term([fake_item])

    # Both original items should still be present
    assert len(memory_manager.short_term) == 2


def test_delete_uses_equality_not_identity(memory_manager):
    """delete_short_term uses Python 'in' operator (dict equality),
    so a copy with equal key-values also matches."""
    memory_manager.add_short_term("q1", {"text": "target"}, session_id="s1")

    original = memory_manager.short_term[0]

    # Build a dict copy that is equal but not the same object
    copy = dict(original)
    assert copy is not original
    assert copy == original

    memory_manager.delete_short_term([copy])

    # The original item should be removed because dict equality matches
    assert len(memory_manager.short_term) == 0


def test_delete_all_items(memory_manager):
    """Deleting every item should leave short_term empty."""
    memory_manager.add_short_term("q1", {"text": "a1"})
    memory_manager.add_short_term("q2", {"text": "a2"})
    memory_manager.add_short_term("q3", {"text": "a3"})

    all_items = list(memory_manager.short_term)
    assert len(all_items) == 3

    memory_manager.delete_short_term(all_items)

    assert memory_manager.short_term == []
    assert len(memory_manager.short_term) == 0


def test_delete_with_realistic_citation_items(memory_manager):
    """delete_short_term works correctly with realistic memory items
    that contain citations and embeddings (from sample_mcp_tool_call_result)."""
    from test.helpers.samples import sample_mcp_tool_call_result

    result = sample_mcp_tool_call_result()
    memory_manager.add_short_term("TOPMOST features", result, session_id="sess-r")
    memory_manager.add_short_term("OCTIS comparison", {"text": "simple"}, session_id="sess-s")

    assert len(memory_manager.short_term) == 2

    rich_item = memory_manager.short_term[0]
    simple_item = memory_manager.short_term[1]

    # Verify the rich item has embeddings from citations
    assert "embeddings" in rich_item
    assert len(rich_item["embeddings"]) >= 1
    assert rich_item["embeddings"][0]["chunk_id"] == "9a08dfd1_0014_24dbbf27"

    # Delete the rich item
    memory_manager.delete_short_term([rich_item])

    assert len(memory_manager.short_term) == 1
    assert memory_manager.short_term[0]["query"] == "OCTIS comparison"
    assert simple_item in memory_manager.short_term
