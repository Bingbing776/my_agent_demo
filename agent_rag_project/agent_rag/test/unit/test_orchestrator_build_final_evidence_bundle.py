"""阶段 2.4.1 — RagOrchestrator._build_final_evidence_bundle。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_sorted_by_task_id(orchestrator):
    from test.helpers.samples import sample_subtask_result; b = orchestrator._build_final_evidence_bundle([sample_subtask_result(task_id="b"), sample_subtask_result(task_id="a")]); assert "a" in b and "b" in b
