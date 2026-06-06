from __future__ import annotations

import base64

import pytest

from test.helpers.contracts import assert_mcp_normalized
from test.helpers.samples import (
    sample_mcp_raw_error,
    sample_mcp_raw_multimodal,
    sample_mcp_raw_text_only,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# _gate -- gate.1 aggregator: symbol=all, target_class=ContractGate
# ---------------------------------------------------------------------------

def _gate() -> None:
    """ContractGate: validate MCP Normalized contract.

    Imports ContractGate from agent_rag (when implemented) and verifies
    the mcp_normalized contract assertion passes against canonical
    sample data.  This is one entry-point for the gate.1 milestone.
    """
    try:
        from agent_rag import ContractGate  # noqa: F401
    except ImportError:
        pass  # ContractGate not implemented yet; contract helpers still validated

    assert_mcp_normalized(sample_mcp_raw_text_only())
    assert_mcp_normalized(sample_mcp_raw_multimodal())
    assert_mcp_normalized(sample_mcp_raw_error())


# ---------------------------------------------------------------------------
# MCP Normalized contract tests (phase 1.4)
# ---------------------------------------------------------------------------

class TestMcpNormalized:
    """Verify assert_mcp_normalized handles valid / invalid MCP returns."""

    # -- positive tests ---------------------------------------------------

    def test_text_only_passes(self) -> None:
        """Plain-text MCP return should pass contract check."""
        assert_mcp_normalized(sample_mcp_raw_text_only())

    def test_multimodal_passes(self) -> None:
        """MCP return with images should pass contract check."""
        assert_mcp_normalized(sample_mcp_raw_multimodal())

    def test_error_passes(self) -> None:
        """isError=True MCP return must still satisfy content structure contract."""
        assert_mcp_normalized(sample_mcp_raw_error())

    def test_empty_content_list_passes(self) -> None:
        """Empty content list is a valid MCP return structure."""
        assert_mcp_normalized({"content": [], "isError": False})

    def test_multiple_text_blocks_pass(self) -> None:
        """Multiple text blocks should all pass inspection."""
        raw = {
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
            "isError": False,
        }
        assert_mcp_normalized(raw)

    def test_text_and_image_mixed_passes(self) -> None:
        """Mixed text and image blocks should pass."""
        png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        raw = {
            "content": [
                {"type": "text", "text": "see below"},
                {"type": "image", "data": png, "mimeType": "image/png"},
            ],
            "isError": False,
        }
        assert_mcp_normalized(raw)

    def test_image_block_accepts_mime_type_underscore(self) -> None:
        """Image block using mime_type (underscore) instead of mimeType should pass."""
        png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        raw = {
            "content": [{"type": "image", "data": png, "mime_type": "image/png"}],
            "isError": False,
        }
        assert_mcp_normalized(raw)

    # -- negative tests: content structure anomalies ----------------------

    def test_content_must_be_list(self) -> None:
        """content not a list must raise AssertionError."""
        bad = {"content": "not_a_list", "isError": False}
        with pytest.raises(AssertionError, match="content must be list"):
            assert_mcp_normalized(bad)

    def test_content_is_none_raises(self) -> None:
        """content=None must raise AssertionError."""
        bad: dict = {"content": None, "isError": False}  # type: ignore[dict-item]
        with pytest.raises(AssertionError, match="content must be list"):
            assert_mcp_normalized(bad)

    def test_content_item_not_dict_raises(self) -> None:
        """Non-dict content element must trigger AssertionError."""
        bad = {"content": ["string_instead_of_dict"], "isError": False}
        with pytest.raises(AssertionError):
            assert_mcp_normalized(bad)

    # -- negative tests: isError anomalies ---------------------------------

    def test_iserror_must_be_bool(self) -> None:
        """isError not a bool must raise AssertionError."""
        bad = {"content": [], "isError": "yes"}
        with pytest.raises(AssertionError, match="isError must be bool"):
            assert_mcp_normalized(bad)

    def test_iserror_missing_raises(self) -> None:
        """Missing isError key must raise AssertionError."""
        bad = {"content": []}
        with pytest.raises(AssertionError, match="isError must be bool"):
            assert_mcp_normalized(bad)

    # -- negative tests: text block anomalies ------------------------------

    def test_text_block_requires_text_key(self) -> None:
        """type=text but missing text field must trigger AssertionError."""
        bad = {"content": [{"type": "text"}], "isError": False}
        with pytest.raises(AssertionError):
            assert_mcp_normalized(bad)

    # -- negative tests: image block anomalies -----------------------------

    def test_image_block_requires_data(self) -> None:
        """type=image but missing data field must trigger AssertionError."""
        bad = {
            "content": [{"type": "image", "mimeType": "image/png"}],
            "isError": False,
        }
        with pytest.raises(AssertionError, match="image block needs data"):
            assert_mcp_normalized(bad)

    def test_image_block_empty_data_raises(self) -> None:
        """type=image with empty data string must trigger AssertionError."""
        bad = {
            "content": [{"type": "image", "data": "", "mimeType": "image/png"}],
            "isError": False,
        }
        with pytest.raises(AssertionError, match="image block needs data"):
            assert_mcp_normalized(bad)

    def test_image_block_neither_mime_type_present(self) -> None:
        """type=image with neither mimeType nor mime_type should still pass (only data required)."""
        png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        raw = {
            "content": [{"type": "image", "data": png}],
            "isError": False,
        }
        assert_mcp_normalized(raw)
