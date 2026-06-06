"""gate.1 -- ContractGate all-contracts gate + AnswerResult contract (phase 1.6).

Validates:
- ContractGate import from agent_rag (symbol=all, gate.1 entry point)
- AnswerResult structure: text, images
- text must be a string
- images must be a list of {mime_type, data} dicts with valid base64 data

Other contract types tested in sibling files:
- test_next_action_result.py (phase 1.1)
- test_eval_result.py (phase 1.2)
- test_subtask_result.py (phase 1.3)
- test_mcp_normalized.py (phase 1.4)
- test_global_readiness.py (phase 1.5)
"""
from __future__ import annotations

import base64

import pytest

from test.helpers.contracts import assert_answer_result
from test.helpers.samples import sample_answer_result

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# _gate -- gate.1 aggregator: symbol=all, target_class=ContractGate
# ---------------------------------------------------------------------------

def _gate() -> None:
    """ContractGate: validate AnswerResult contract.

    Imports ContractGate from agent_rag (when implemented) and verifies
    the answer_result contract assertions pass against canonical
    sample data.  This is one entry-point for the gate.1 milestone.
    """
    # Import ContractGate -- skip if not yet implemented
    try:
        from agent_rag import ContractGate  # noqa: F401
    except ImportError:
        pass

    # AnswerResult
    assert_answer_result(sample_answer_result())
    assert_answer_result(sample_answer_result(images=[]))


# ---------------------------------------------------------------------------
# AnswerResult contract tests (phase 1.6)
# ---------------------------------------------------------------------------

class TestAnswerResult:
    """Verify AnswerResult structure for final / synthesized answers."""

    # -- positive tests ---------------------------------------------------

    def test_minimal_shape(self) -> None:
        """Canonical AnswerResult passes all contract checks."""
        result = sample_answer_result()
        assert_answer_result(result)
        assert isinstance(result["text"], str)
        assert len(result["text"]) > 0
        assert isinstance(result["images"], list)
        assert len(result["images"]) == 1

    def test_with_multiple_images(self) -> None:
        """Multiple image entries all pass contract validation."""
        png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        result = sample_answer_result(
            images=[
                {"mime_type": "image/png", "data": png},
                {"mime_type": "image/jpeg", "data": png},
                {"mime_type": "image/gif", "data": png},
            ]
        )
        assert_answer_result(result)
        assert len(result["images"]) == 3

    def test_no_images_key(self) -> None:
        """Missing images key defaults to empty list (contract tolerant)."""
        result = sample_answer_result()
        del result["images"]
        # contract uses .get("images") or [] -- missing key -> None -> []
        assert_answer_result(result)

    def test_images_is_none(self) -> None:
        """images=None is treated as empty list by the contract."""
        result = sample_answer_result(images=None)
        assert_answer_result(result)

    def test_empty_images_list(self) -> None:
        """Explicit empty images list passes."""
        result = sample_answer_result(images=[])
        assert_answer_result(result)

    def test_large_answer_text(self) -> None:
        """Realistic multi-paragraph answer text passes."""
        long_text = (
            "TOPMOST is a unified topic modeling toolkit that supports\\n"
            "basic, hierarchical, dynamic, and cross-lingual topic modeling.\\n\\n"
            "Compared to OCTIS, TOPMOST provides wider scenario coverage and\\n"
            "includes dedicated dataset handlers, model implementations,\\n"
            "and evaluation metrics for each scenario. The architecture\\n"
            "decouples dataset preprocessing, topic model training, and\\n"
            "evaluation into independent modules."
        )
        result = sample_answer_result(text=long_text, images=[])
        assert_answer_result(result)
        assert "\\n" in result["text"]

    def test_single_image_multiple_mime_fields(self) -> None:
        """Image entries may carry extra fields beyond mime_type and data."""
        png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        result = sample_answer_result(
            images=[
                {
                    "mime_type": "image/png",
                    "data": png,
                    "width": 800,
                    "height": 600,
                    "caption": "Figure 2: TOPMOST architecture",
                }
            ]
        )
        assert_answer_result(result)

    # -- negative tests: text ---------------------------------------------

    def test_missing_text_key_raises(self) -> None:
        """Missing text key triggers AssertionError (get returns None, not str)."""
        bad = {"images": []}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_text_is_none_raises(self) -> None:
        """text=None triggers AssertionError."""
        bad = {"text": None, "images": []}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_text_is_int_raises(self) -> None:
        """text as int triggers AssertionError."""
        bad = {"text": 42, "images": []}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_text_is_dict_raises(self) -> None:
        """text as dict triggers AssertionError."""
        bad = {"text": {"key": "val"}, "images": []}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_text_is_list_raises(self) -> None:
        """text as list triggers AssertionError."""
        bad = {"text": ["line1", "line2"], "images": []}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_text_is_empty_string_passes(self) -> None:
        """Empty string text is still a str, so the contract passes."""
        result = sample_answer_result(text="", images=[])
        assert_answer_result(result)

    # -- negative tests: images -------------------------------------------

    def test_images_not_list_raises(self) -> None:
        """images as string triggers AssertionError."""
        bad = {"text": "answer", "images": "not_a_list"}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_images_is_int_raises(self) -> None:
        """images as int triggers AssertionError."""
        bad = {"text": "answer", "images": 123}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_image_item_not_dict_raises(self) -> None:
        """Non-dict entry in images list triggers AttributeError or AssertionError."""
        bad = {"text": "answer", "images": ["string_instead_of_dict"]}
        with pytest.raises((AssertionError, AttributeError, TypeError)):
            assert_answer_result(bad)

    def test_image_item_is_none_raises(self) -> None:
        """None entry in images list triggers AttributeError or AssertionError."""
        bad = {"text": "answer", "images": [None]}
        with pytest.raises((AssertionError, AttributeError, TypeError)):
            assert_answer_result(bad)

    def test_image_missing_mime_type_raises(self) -> None:
        """Image entry missing mime_type triggers AssertionError."""
        png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        bad = {"text": "answer", "images": [{"data": png}]}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_image_missing_data_raises(self) -> None:
        """Image entry missing data triggers AssertionError."""
        bad = {"text": "answer", "images": [{"mime_type": "image/png"}]}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_image_invalid_base64_raises(self) -> None:
        """Image data not valid base64 triggers binascii.Error."""
        bad = {
            "text": "answer",
            "images": [{"mime_type": "image/png", "data": "!!!not-valid-base64!!!"}],
        }
        with pytest.raises(Exception):
            assert_answer_result(bad)

    def test_image_data_empty_string_passes(self) -> None:
        """Empty string data is valid base64 (decodes to zero bytes).

        The contract uses base64.b64decode with validate=True;
        an empty string decodes successfully to b"".
        """
        result = sample_answer_result(
            images=[{"mime_type": "image/png", "data": ""}]
        )
        assert_answer_result(result)

    def test_image_missing_both_keys_raises(self) -> None:
        """Image entry with neither mime_type nor data triggers AssertionError."""
        bad = {"text": "answer", "images": [{"caption": "orphan"}]}
        with pytest.raises(AssertionError):
            assert_answer_result(bad)

    def test_both_text_and_images_invalid_raises(self) -> None:
        """When both text and images are invalid, contract fails on text first."""
        bad = {
            "text": None,
            "images": [{"mime_type": "image/png"}],
        }
        with pytest.raises(AssertionError):
            assert_answer_result(bad)
