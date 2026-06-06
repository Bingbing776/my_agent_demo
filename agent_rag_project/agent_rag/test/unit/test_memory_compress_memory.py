import pytest

from agent_rag.memory.memory_manager import MemoryManager
from test.helpers.samples import sample_mcp_tool_call_result

pytestmark = [pytest.mark.unit]


def test_returns_tuple(memory_manager):
    """compress_memory returns (str, List[float]) with compressed text and embedding."""
    # Realistic evidence data with citations at top level,
    # patterned after sample_mcp_tool_call_result citation format
    result = {
        "citations": [
            {
                "chunk_id": "9a08dfd1_0014_24dbbf27",
                "text_snippet": "TOPMOST reaches a wider coverage",
            },
            {
                "chunk_id": "9a08dfd1_0007_2c9d39fa",
                "text_snippet": "we introduce TOPMOST",
            },
        ]
    }
    compressed_text, embedding = memory_manager.compress_memory(result)

    # Verify return type: must be (str, list)
    assert isinstance(compressed_text, str), "compressed text must be a string"
    assert isinstance(embedding, list), "embedding must be a list"

    # Embedding must be a non-empty list of floats
    assert len(embedding) > 0, "embedding must be non-empty"
    for val in embedding:
        assert isinstance(val, float), (
            f"embedding element must be float, got {type(val)}"
        )

    # With citations containing text_snippets, compressed text must be non-empty
    assert len(compressed_text) > 0, (
        "compressed text must be non-empty when input has evidence chunks"
    )

    # Compressed text should preserve key terms from evidence
    assert (
        "TOPMOST" in compressed_text
        or "coverage" in compressed_text
        or "introduce" in compressed_text
    ), (
        "compressed text should contain key terms from evidence; "
        f"got: {compressed_text!r}"
    )

    # Empty result: should return empty string and embedding vector
    empty_text, empty_embedding = memory_manager.compress_memory({})
    assert empty_text == "", (
        "empty result should yield empty compressed text; "
        f"got: {empty_text!r}"
    )
    assert isinstance(empty_embedding, list)
    assert len(empty_embedding) > 0, (
        "empty result embedding must not be empty"
    )
    for val in empty_embedding:
        assert isinstance(val, float), (
            "empty result embedding elements must be float"
        )
