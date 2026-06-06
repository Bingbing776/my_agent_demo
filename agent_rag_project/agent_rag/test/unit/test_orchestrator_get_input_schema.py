"""阶段 8.1.3 — RagOrchestrator.get_input_schema。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_from_cache(orchestrator):
    orchestrator._tools_by_name = {"t": {"inputSchema": {"type": "object"}}}; assert orchestrator.get_input_schema("t")
