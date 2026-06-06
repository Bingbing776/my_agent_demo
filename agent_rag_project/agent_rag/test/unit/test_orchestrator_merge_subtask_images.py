"""阶段 2.4.2 — RagOrchestrator._merge_subtask_images。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_dedupe_by_data(orchestrator):
    from test.helpers.samples import sample_answer_result; img = sample_answer_result()["images"][0]; merged = orchestrator._merge_subtask_images([[img], [img]]); assert len(merged) == 1
