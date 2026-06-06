"""Phase 5.2 - MemoryManager.compute_memory_similarity. See docs/test_outline.md"""
import pytest

from test.helpers.samples import sample_mcp_tool_call_result

pytestmark = [pytest.mark.unit]


def test_empty_chunks(memory_manager):
    """Empty chunks list returns (0.0, [])."""
    score, embeddings = memory_manager.compute_memory_similarity([], "any query")
    assert score == 0.0
    assert embeddings == []
    assert isinstance(score, float)
    assert isinstance(embeddings, list)


def test_returns_tuple_of_two(memory_manager):
    """Return value is a 2-tuple of (float, list)."""
    chunks = [{"text_snippet": "hello world", "chunk_id": "c1", "source": "doc1"}]
    result = memory_manager.compute_memory_similarity(chunks, "hello")
    assert isinstance(result, tuple)
    assert len(result) == 2
    score, embeddings = result
    assert isinstance(score, float)
    assert isinstance(embeddings, list)


def test_single_chunk_with_text_snippet(memory_manager):
    """Chunk with text_snippet: body extracted via _evidence_body, embedding generated."""
    chunks = [{"text_snippet": "TOPMOST reaches a wider coverage", "chunk_id": "9a08dfd1_0014_24dbbf27", "source": "2024.acl-demos.4.pdf"}]
    query = "TOPMOST topic modeling toolkit"
    score, embeddings = memory_manager.compute_memory_similarity(chunks, query)
    assert 0.0 <= score <= 1.0
    assert len(embeddings) == 1
    emb = embeddings[0]
    assert emb["chunk_id"] == "9a08dfd1_0014_24dbbf27"
    assert emb["source"] == "2024.acl-demos.4.pdf"
    assert isinstance(emb["embedding"], list)
    assert len(emb["embedding"]) > 0


def test_chunk_falls_back_to_text_field(memory_manager):
    """When text_snippet is absent, _evidence_body falls back to text field."""
    chunks = [{"text": "We introduce TOPMOST, a toolkit for topic modeling.", "chunk_id": "c2", "source": "paper.pdf"}]
    query = "topic modeling"
    score, embeddings = memory_manager.compute_memory_similarity(chunks, query)
    assert 0.0 <= score <= 1.0
    assert len(embeddings) == 1
    assert embeddings[0]["chunk_id"] == "c2"


def test_all_chunks_empty_body_returns_zero_score(memory_manager):
    """When every chunk yields empty body (no text_snippet, no text), score is 0.0.

    Embedding list is still returned so callers can inspect chunk metadata.
    """
    chunks = [
        {"chunk_id": "c1", "source": "doc1"},
        {"chunk_id": "c2", "source": "doc2"},
    ]
    query = "irrelevant query"
    score, embeddings = memory_manager.compute_memory_similarity(chunks, query)
    assert score == 0.0
    assert len(embeddings) == 2
    for emb in embeddings:
        assert "chunk_id" in emb
        assert "source" in emb
        assert "embedding" in emb


def test_mixed_valid_and_empty_chunks(memory_manager):
    """Chunks with valid text contribute to score; empty-body chunks get embeddings but not scored."""
    chunks = [
        {"text_snippet": "valid evidence text", "chunk_id": "c1", "source": "doc1"},
        {"chunk_id": "c2", "source": "doc2"},  # empty body
        {"text_snippet": "another valid snippet", "chunk_id": "c3", "source": "doc3"},
    ]
    query = "evidence"
    score, embeddings = memory_manager.compute_memory_similarity(chunks, query)
    assert 0.0 <= score <= 1.0
    assert len(embeddings) == 3
    # All three chunks get embedding entries regardless of body
    chunk_ids = {emb["chunk_id"] for emb in embeddings}
    assert chunk_ids == {"c1", "c2", "c3"}


def test_score_bounded_between_zero_and_one(memory_manager):
    """No matter the input, returned score must be in [0, 1]."""
    chunks = [{"text_snippet": "sample text for scoring", "chunk_id": "c1", "source": "src"}]
    queries = ["exact match", "completely unrelated", ""]
    for q in queries:
        score, _ = memory_manager.compute_memory_similarity(chunks, q)
        assert 0.0 <= score <= 1.0, f"score {score} out of bounds for query {q!r}"


def test_empty_query_string_handled(memory_manager):
    """Empty query string should not crash; score stays in [0, 1]."""
    chunks = [{"text_snippet": "some content", "chunk_id": "c1", "source": "s"}]
    score, embeddings = memory_manager.compute_memory_similarity(chunks, "")
    assert 0.0 <= score <= 1.0
    assert len(embeddings) == 1


def test_uses_real_citation_data_from_knowledge_hub(memory_manager):
    """Integration-style: use realistic citation shapes from MCP query_knowledge_hub."""
    tool_result = sample_mcp_tool_call_result()
    citations = tool_result["structuredContent"]["citations"]
    assert len(citations) >= 2, "test data must have at least 2 citations"

    query = "TOPMOST topic modeling coverage"
    score, embeddings = memory_manager.compute_memory_similarity(citations, query)
    assert 0.0 <= score <= 1.0
    assert len(embeddings) == len(citations)
    for i, emb in enumerate(embeddings):
        assert emb["chunk_id"] == citations[i]["chunk_id"]
        assert isinstance(emb["embedding"], list)
        assert len(emb["embedding"]) > 0
