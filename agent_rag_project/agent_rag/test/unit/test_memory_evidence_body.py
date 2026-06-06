"""MemoryManager._evidence_body unit tests."""
import pytest

pytestmark = [pytest.mark.unit]


def test_text_snippet_preferred(memory_manager):
    assert memory_manager._evidence_body({"text_snippet": "a", "text": "b"}) == "a"


def test_fallback_text(memory_manager):
    assert memory_manager._evidence_body({"text": "only"}) == "only"


def test_empty_returns_empty(memory_manager):
    assert memory_manager._evidence_body({}) == ""
