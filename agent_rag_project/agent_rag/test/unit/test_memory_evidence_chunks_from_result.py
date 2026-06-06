"""Phase 2.1.2 - MemoryManager._evidence_chunks_from_result. See docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]


def test_multiple_citations(memory_manager):
    """When result has citations, return all non-empty citations as chunks."""
    r = {
        "citations": [
            {"text_snippet": "first cite", "chunk_id": "c1"},
            {"text_snippet": "second cite", "chunk_id": "c2"},
        ]
    }
    out = memory_manager._evidence_chunks_from_result(r)
    assert len(out) == 2
    assert out[0]["text_snippet"] == "first cite"
    assert out[0]["chunk_id"] == "c1"
    assert out[1]["text_snippet"] == "second cite"
    assert out[1]["chunk_id"] == "c2"


def test_top_level_text_when_no_citations(memory_manager):
    """When no citations key exists, wrap top-level text into a single chunk."""
    out = memory_manager._evidence_chunks_from_result({"text": "body"})
    assert len(out) == 1
    assert out[0]["text_snippet"] == "body"


def test_empty_result(memory_manager):
    """Empty dict returns empty list."""
    assert memory_manager._evidence_chunks_from_result({}) == []


def test_skip_empty_body(memory_manager):
    """Citations whose body (via _evidence_body) is empty are skipped."""
    r = {
        "citations": [
            {"text_snippet": "  valid  ", "chunk_id": "c1"},
            {"text_snippet": "", "text": "", "chunk_id": "c2"},
            {"chunk_id": "c3"},
        ]
    }
    out = memory_manager._evidence_chunks_from_result(r)
    assert len(out) == 1
    assert out[0]["chunk_id"] == "c1"
    assert out[0]["text_snippet"] == "valid"


def test_citation_fallback_to_text(memory_manager):
    """Within a citation, fallback from text_snippet to text field via _evidence_body."""
    r = {
        "citations": [
            {"text": "fallback body", "chunk_id": "c1"},
        ]
    }
    out = memory_manager._evidence_chunks_from_result(r)
    assert len(out) == 1
    assert out[0]["text_snippet"] == "fallback body"


def test_citations_preferred_over_top_level_text(memory_manager):
    """When both citations and top-level text exist, citations take precedence."""
    r = {
        "citations": [{"text_snippet": "from citation", "chunk_id": "c1"}],
        "text": "ignored top-level text",
    }
    out = memory_manager._evidence_chunks_from_result(r)
    assert len(out) == 1
    assert out[0]["text_snippet"] == "from citation"
    assert out[0]["chunk_id"] == "c1"


def test_empty_citations_falls_back_to_text(memory_manager):
    """When citations list is empty, fall back to top-level text."""
    r = {
        "citations": [],
        "text": "top-level body",
    }
    out = memory_manager._evidence_chunks_from_result(r)
    assert len(out) == 1
    assert out[0]["text_snippet"] == "top-level body"


def test_all_citations_empty_returns_empty_list(memory_manager):
    """When all citations have empty bodies and no top-level text, return []."""
    r = {
        "citations": [
            {"text_snippet": "", "text": ""},
            {},
        ]
    }
    out = memory_manager._evidence_chunks_from_result(r)
    assert out == []
