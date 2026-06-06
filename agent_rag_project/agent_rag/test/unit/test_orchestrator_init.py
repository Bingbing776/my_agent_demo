"""阶段 8.1.1 — RagOrchestrator.__init__。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_constructs(orchestrator):
    assert orchestrator is not None
