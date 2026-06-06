import pytest
from datetime import datetime
from unittest.mock import patch

pytestmark = [pytest.mark.unit]


def test_adds_item(memory_manager):
    """Verify add_short_term stores items with correct structure, session_id,
    score logic, embeddings, and capacity-based eviction."""

    # 1. Basic add: item appears in short_term list
    memory_manager.add_short_term("test query", {"text": "answer text"})
    assert len(memory_manager.short_term) >= 1

    item = memory_manager.short_term[-1]

    # 2. All required keys present in memory_item
    for key in ("query", "result", "session_id", "timestamp", "score",
                "access_count", "embeddings"):
        assert key in item, f"missing required key: {key}"

    # 3. query and result are preserved exactly
    assert item["query"] == "test query"
    assert item["result"] == {"text": "answer text"}

    # 4. session_id is auto-generated when not provided (non-empty string)
    assert isinstance(item["session_id"], str)
    assert len(item["session_id"]) > 0

    # 5. timestamp is a datetime instance
    assert isinstance(item["timestamp"], datetime)

    # 6. access_count initialised to 0
    assert item["access_count"] == 0

    # 7. score defaults to 0.5 when result dict lacks "score" key
    assert item["score"] == 0.5

    # 8. embeddings is a list (may be empty for result with no citations/text)
    assert isinstance(item["embeddings"], list)

    # 9. Explicit session_id is preserved
    memory_manager.add_short_term("q2", {"text": "a2"}, session_id="my-session")
    item2 = memory_manager.short_term[-1]
    assert item2["session_id"] == "my-session"

    # 10. When result has "score" key, memory_item.score = computed_score.
    #     We patch compute_memory_similarity to return a deterministic value
    #     (0.0, []) so the assertion does not depend on encoder internals.
    with patch.object(
        memory_manager, "compute_memory_similarity", return_value=(0.0, [])
    ):
        memory_manager.add_short_term("q3", {"text": "a3", "score": 0.9})
    item3 = memory_manager.short_term[-1]
    assert item3["score"] == 0.0, (
        "When result has 'score' key, item['score'] must equal computed_score "
        "(0.0 from patched compute_memory_similarity), not result['score']"
    )

    # 11. Capacity eviction: oldest items removed when limit exceeded
    from agent_rag.memory.memory_manager import MemoryManager
    mm_small = MemoryManager(config={"short_term_capacity": 2})
    mm_small.add_short_term("first", {"text": "one"})
    mm_small.add_short_term("second", {"text": "two"})
    assert len(mm_small.short_term) == 2

    mm_small.add_short_term("third", {"text": "three"})
    assert len(mm_small.short_term) == 2
    # oldest item ("first") should be evicted
    assert mm_small.short_term[0]["query"] == "second"
    assert mm_small.short_term[1]["query"] == "third"

    # 12. Realistic result with top-level citations produces correct embeddings
    memory_manager.add_short_term(
        "TOPMOST features",
        {
            "citations": [
                {
                    "chunk_id": "9a08dfd1_0014_24dbbf27",
                    "source": "2024.acl-demos.4.pdf",
                    "text_snippet": "TOPMOST reaches a wider coverage",
                },
                {
                    "chunk_id": "9a08dfd1_0007_2c9d39fa",
                    "source": "2024.acl-demos.4.pdf",
                    "text": "we introduce TOPMOST",
                },
            ]
        },
        session_id="sess-real",
    )
    item_real = memory_manager.short_term[-1]
    assert item_real["session_id"] == "sess-real"
    assert len(item_real["embeddings"]) == 2
    assert item_real["embeddings"][0]["chunk_id"] == "9a08dfd1_0014_24dbbf27"
    assert item_real["embeddings"][1]["chunk_id"] == "9a08dfd1_0007_2c9d39fa"
    assert item_real["embeddings"][0]["source"] == "2024.acl-demos.4.pdf"
    # each embedding entry must have an "embedding" key with a list of floats
    assert isinstance(item_real["embeddings"][0]["embedding"], list)
    assert len(item_real["embeddings"][0]["embedding"]) > 0

    # 13. Result with no citations and no text produces empty embeddings
    memory_manager.add_short_term("empty", {}, session_id="sess-empty")
    item_empty = memory_manager.short_term[-1]
    assert item_empty["embeddings"] == []
    assert item_empty["score"] == 0.5
