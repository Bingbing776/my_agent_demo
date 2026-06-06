"""阶段 2.4.3 — RagOrchestrator._should_attach_images。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_no_images_false(orchestrator):
    assert orchestrator._should_attach_images([], "query") is False
