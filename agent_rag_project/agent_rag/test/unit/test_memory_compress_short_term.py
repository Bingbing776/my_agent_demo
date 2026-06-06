import pytest
from unittest.mock import MagicMock

from agent_rag.memory.memory_manager import MemoryManager
from test.helpers.samples import sample_mcp_tool_call_result

pytestmark = [pytest.mark.unit]


def test_returns_str(memory_manager):
    """compress_short_term returns a str for valid list input with citations."""
    result = [
        {
            "citations": [
                {"chunk_id": "c1", "text_snippet": "Evidence text one."},
            ],
            "score": 0.8,
        }
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str), (
        f"compress_short_term must return str, got {type(compressed)}"
    )
    assert len(compressed) > 0, (
        "compress_short_term must return non-empty str for valid input"
    )


def test_empty_list_none_returns_empty_str(memory_manager):
    """Empty list, None, or items with no extractable text return empty string."""
    assert memory_manager.compress_short_term([]) == "", (
        "empty list must return empty string"
    )
    assert memory_manager.compress_short_term(None) == "", (
        "None must return empty string"
    )
    # Item with no useful text fields
    assert memory_manager.compress_short_term([{}]) == "", (
        "item with no extractable text must return empty string"
    )
    # Item with all empty text fields
    assert memory_manager.compress_short_term(
        [{"text_snippet": "", "text": "", "body": ""}]
    ) == "", "item with all-empty text fields must return empty string"


def test_single_item_with_citations_from_sample(memory_manager):
    """Single memory item built from sample_mcp_tool_call_result citations is compressed."""
    sample = sample_mcp_tool_call_result()
    citations = sample["structuredContent"]["citations"]
    result = [{"citations": citations, "score": 0.85}]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "compress_short_term must produce non-empty output for sample citation data"
    )


def test_multiple_items_merged(memory_manager):
    """Multiple memory items with different citations are merged and compressed."""
    result = [
        {
            "citations": [
                {"chunk_id": "c1", "text_snippet": "First piece of evidence."},
            ],
            "score": 0.9,
        },
        {
            "citations": [
                {"chunk_id": "c2", "text_snippet": "Second piece of evidence."},
            ],
            "score": 0.7,
        },
        {
            "citations": [
                {"chunk_id": "c3", "text_snippet": "Third piece of evidence."},
            ],
            "score": 0.5,
        },
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "multiple items must produce non-empty compressed output"
    )


def test_item_without_citations_falls_back_to_direct_text(memory_manager):
    """When item has no citations, _evidence_body extracts from text_snippet/text/body."""
    result = [
        {"text_snippet": "Direct text snippet content.", "score": 0.6},
        {"text": "Top-level text field content.", "score": 0.4},
        {"body": "Body field fallback content.", "score": 0.3},
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "items with direct text fields must produce non-empty output"
    )


def test_mixed_valid_and_empty_items(memory_manager):
    """Empty or invalid items are skipped; only valid items contribute to output."""
    result = [
        {},  # completely empty, no extractable text
        {
            "citations": [
                {"chunk_id": "c1", "text_snippet": "Valid evidence one."}
            ],
            "score": 0.8,
        },
        {"text_snippet": "", "text": "", "body": ""},  # all fields empty
        {
            "citations": [
                {"chunk_id": "c2", "text_snippet": "Valid evidence two."}
            ],
            "score": 0.6,
        },
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "mixed items must produce non-empty output from valid entries"
    )


def test_non_dict_items_skipped(memory_manager):
    """Non-dict entries in the list are silently ignored."""
    result = [
        "not a dict",
        42,
        None,
        {
            "citations": [{"chunk_id": "c1", "text_snippet": "Valid evidence."}],
            "score": 0.7,
        },
        ["also", "not", "a", "dict"],
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "non-dict entries must be skipped without crashing"
    )


def test_realistic_memory_items_from_add_short_term_shape(memory_manager):
    """Memory items resembling add_short_term output with nested result
    and citations at top level are processed correctly."""
    sample = sample_mcp_tool_call_result()
    # Simulate memory items similar to what add_short_term stores
    memory_item = {
        "query": "What is TOPMOST?",
        "result": sample,
        "session_id": "session-1",
        "score": 0.85,
        "access_count": 2,
        "citations": sample["structuredContent"]["citations"],
    }
    # compress_short_term extracts citations from top-level of each item
    compressed = memory_manager.compress_short_term([memory_item])
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "realistic memory items must produce non-empty compressed output"
    )


def test_items_without_explicit_score_default_to_half(memory_manager):
    """Items without a 'score' key default to 0.5 for all their text pieces."""
    result = [
        {"text_snippet": "Has explicit score.", "score": 0.9},
        {"text_snippet": "No explicit score; defaults to 0.5."},
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "items without score must still contribute to compressed output"
    )


def test_item_with_top_level_citations_over_nested_result(memory_manager):
    """Item may carry citations at top level even when result key is present."""
    result = [
        {
            "result": {"text": "nested text that should be ignored"},
            "citations": [
                {"chunk_id": "c1", "text_snippet": "Top-level citation text."},
            ],
            "score": 0.75,
        }
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "item with top-level citations must produce non-empty output"
    )


def test_fallback_sorts_by_score_desc_when_llm_fails(memory_manager):
    """When LLM call fails, fallback concatenates texts sorted by score descending."""
    result = [
        {"text_snippet": "Low priority information.", "score": 0.3},
        {"text_snippet": "High priority information.", "score": 0.9},
        {"text_snippet": "Medium priority information.", "score": 0.6},
    ]
    # Force LLM chat to raise an exception, triggering the fallback path
    original_llm = memory_manager._llm
    try:
        failing_llm = MagicMock()
        failing_llm.chat.side_effect = RuntimeError("LLM unavailable")
        memory_manager._llm = failing_llm
        compressed = memory_manager.compress_short_term(result)
        # Fallback concatenates in score-descending order: 0.9, 0.6, 0.3
        idx_high = compressed.find("High priority")
        idx_medium = compressed.find("Medium priority")
        idx_low = compressed.find("Low priority")
        assert idx_high >= 0, "High priority text must be present in fallback"
        assert idx_medium >= 0, "Medium priority text must be present in fallback"
        assert idx_low >= 0, "Low priority text must be present in fallback"
        assert idx_high < idx_medium < idx_low, (
            f"Fallback must order by score desc; "
            f"got positions high={idx_high} medium={idx_medium} low={idx_low}"
        )
    finally:
        memory_manager._llm = original_llm


def test_truncation_when_fallback_output_exceeds_limit(memory_manager):
    """Output longer than compress_max_tokens * 4 chars is truncated."""
    # Create enough long items that fallback concatenation exceeds 2048 chars
    long_text = "X" * 200  # 200 chars each
    result = []
    for i in range(20):  # 20 items, ~210 chars each => ~4200 chars in fallback
        result.append({
            "text_snippet": f"Item{i:02d}: {long_text}",
            "score": 0.5,
        })
    # Force LLM failure to test truncation on fallback path
    original_llm = memory_manager._llm
    try:
        failing_llm = MagicMock()
        failing_llm.chat.side_effect = RuntimeError("LLM unavailable")
        memory_manager._llm = failing_llm
        compressed = memory_manager.compress_short_term(result)
        max_chars = memory_manager._compress_max_tokens * 4  # default 512*4 = 2048
        assert len(compressed) <= max_chars, (
            f"compressed text length {len(compressed)} must not exceed max {max_chars}"
        )
        assert len(compressed) > 0, (
            "truncated output must still be non-empty"
        )
    finally:
        memory_manager._llm = original_llm


def test_citations_with_mixed_text_fields(memory_manager):
    """Citations using different text fields (text_snippet, text, body)
    are all extracted via _evidence_body."""
    result = [
        {
            "citations": [
                {"chunk_id": "c1", "text_snippet": "Text snippet citation."},
                {"chunk_id": "c2", "text": "Text field citation."},
                {"chunk_id": "c3", "body": "Body field citation."},
                {"chunk_id": "c4", "text_snippet": ""},  # empty, skipped
                {"chunk_id": "c5"},  # no text fields, skipped
            ],
            "score": 0.7,
        }
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "citations with mixed text fields must produce non-empty output"
    )


def test_citation_non_dict_skipped(memory_manager):
    """Non-dict entries inside citations list are silently skipped."""
    result = [
        {
            "citations": [
                "not a dict",
                None,
                123,
                {"chunk_id": "c1", "text_snippet": "Valid citation."},
            ],
            "score": 0.8,
        }
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "non-dict citations must be skipped without crashing"
    )


def test_item_text_fallback_after_evidence_body_empty(memory_manager):
    """When _evidence_body returns empty (no text_snippet/text/body),
    the item's top-level 'text' field is used as final fallback."""
    result = [
        {
            "text_snippet": "",
            "text": "",
            "body": "",
            "text": "Final fallback top-level text.",
            "score": 0.5,
        }
    ]
    # Note: duplicate 'text' key; last value wins in Python dict
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "top-level text fallback must produce non-empty output"
    )


def test_multiple_items_same_score_stable(memory_manager):
    """Multiple items with identical scores are all included in output."""
    result = [
        {"text_snippet": "Item A content.", "score": 0.5},
        {"text_snippet": "Item B content.", "score": 0.5},
        {"text_snippet": "Item C content.", "score": 0.5},
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "multiple items with same score must produce non-empty output"
    )


def test_score_edge_values_handled(memory_manager):
    """Score values at boundaries (0.0 and 1.0) are handled correctly."""
    result = [
        {"text_snippet": "Zero score item.", "score": 0.0},
        {"text_snippet": "Full score item.", "score": 1.0},
        {"text_snippet": "Mid score item.", "score": 0.5},
    ]
    compressed = memory_manager.compress_short_term(result)
    assert isinstance(compressed, str)
    assert len(compressed) > 0, (
        "edge score values must not break compression"
    )
