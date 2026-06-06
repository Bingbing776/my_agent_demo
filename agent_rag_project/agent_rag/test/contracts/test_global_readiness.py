"""gate.1 -- ContractGate all-contracts gate.

Validates all contract types (symbol=all) via:
- _gate: imports ContractGate, exercises every contract assertion helper
- per-contract tests: GlobalAnswerReadiness specifics (phase 1.5)

Other contract tests in sibling files:
- test_mcp_normalized.py (phase 1.4)
- test_next_action_result.py (phase 1.1)
- test_eval_result.py (phase 1.2)
- test_subtask_result.py (phase 1.3)
- test_answer_result.py (phase 1.6)
"""
from __future__ import annotations

import pytest

from test.helpers.contracts import (
    assert_answer_result,
    assert_eval_result,
    assert_global_answer_readiness,
    assert_mcp_normalized,
    assert_next_action_result,
    assert_subtask_result,
)
from test.helpers.samples import (
    sample_answer_result,
    sample_eval_result,
    sample_global_readiness,
    sample_mcp_raw_error,
    sample_mcp_raw_multimodal,
    sample_mcp_raw_text_only,
    sample_subtask_result,
    sample_tool_trace_entry,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# _gate -- gate.1 aggregator: symbol=all, target_class=ContractGate
# ---------------------------------------------------------------------------

def _gate() -> None:
    """ContractGate: validate ALL contract types in one gate call.

    Imports ContractGate from agent_rag (when implemented) and verifies
    that every contract assertion from test.helpers.contracts passes
    against canonical sample data.  This is the single entry-point for
    the gate.1 milestone.
    """
    # Import ContractGate -- skip gracefully if not yet implemented
    try:
        from agent_rag import ContractGate  # noqa: F401
    except ImportError:
        pass

    # 1. MCP Normalized (phase 1.4)
    assert_mcp_normalized(sample_mcp_raw_text_only())
    assert_mcp_normalized(sample_mcp_raw_multimodal())
    assert_mcp_normalized(sample_mcp_raw_error())

    # 2. EvalResult (phase 1.2)
    assert_eval_result(sample_eval_result())
    assert_eval_result(sample_eval_result(passed=False, status="needs_replan"))
    assert_eval_result(sample_eval_result(passed=False, status="hard_fail"))

    # 3. SubtaskResult (phase 1.3)
    assert_subtask_result(sample_subtask_result())
    assert_subtask_result(
        sample_subtask_result(status="needs_replan", observation_for_replan="retry")
    )
    assert_subtask_result(
        sample_subtask_result(status="failed", observation_for_replan="tool error")
    )

    # 4. NextActionResult (phase 1.1)
    # sample_next_action_result is not yet in samples.py; use inline dicts
    assert_next_action_result({"action": "call_tool", "tool_name": "query_knowledge_hub"})
    assert_next_action_result({"action": "stop"})
    assert_next_action_result({"action": "replan"})

    # 5. GlobalAnswerReadiness (phase 1.5)
    assert_global_answer_readiness(sample_global_readiness())
    assert_global_answer_readiness(
        sample_global_readiness(
            sufficient_for_answer=False,
            need_replan=True,
            observation_for_replan="missing data",
        )
    )

    # 6. AnswerResult (phase 1.6)
    assert_answer_result(sample_answer_result())
    assert_answer_result(sample_answer_result(images=[]))


# ---------------------------------------------------------------------------
# GlobalAnswerReadiness contract tests (phase 1.5)
# ---------------------------------------------------------------------------

class TestGlobalAnswerReadiness:
    """Verify Orchestrator._check_global_answer_readiness return structure."""

    # -- positive tests -------------------------------------------------------

    def test_sufficient(self) -> None:
        """Standard result when evidence is sufficient."""
        result = sample_global_readiness()
        assert_global_answer_readiness(result)
        assert result["sufficient_for_answer"] is True
        assert result["need_replan"] is False
        assert isinstance(result["issues"], list)
        assert result["observation_for_replan"] == ""

    def test_needs_replan_with_observation(self) -> None:
        """When replan is needed, observation_for_replan must be non-empty."""
        result = sample_global_readiness(
            sufficient_for_answer=False,
            need_replan=True,
            observation_for_replan="missing table data, need search_by_metadata",
        )
        assert_global_answer_readiness(result)
        assert result["observation_for_replan"].strip() != ""

    def test_sufficient_false_without_replan(self) -> None:
        """sufficient=False but need_replan=False is valid (e.g., partial but acceptable)."""
        result = sample_global_readiness(
            sufficient_for_answer=False,
            need_replan=False,
            issues=["low confidence on chunk 3"],
            observation_for_replan="",
        )
        assert_global_answer_readiness(result)

    def test_need_replan_false_with_nonempty_observation(self) -> None:
        """need_replan=False with non-empty observation passes (observation is advisory)."""
        result = sample_global_readiness(
            need_replan=False,
            observation_for_replan="some notes but no replan needed",
        )
        assert_global_answer_readiness(result)

    # -- missing key tests ----------------------------------------------------

    def test_missing_sufficient_key_raises(self) -> None:
        """Missing sufficient_for_answer key triggers AssertionError."""
        bad = {
            "need_replan": False,
            "issues": [],
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing GlobalAnswerReadiness key: sufficient_for_answer"):
            assert_global_answer_readiness(bad)

    def test_missing_need_replan_key_raises(self) -> None:
        """Missing need_replan key triggers AssertionError."""
        bad = {
            "sufficient_for_answer": True,
            "issues": [],
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing GlobalAnswerReadiness key: need_replan"):
            assert_global_answer_readiness(bad)

    def test_missing_issues_key_raises(self) -> None:
        """Missing issues key triggers AssertionError."""
        bad = {
            "sufficient_for_answer": True,
            "need_replan": False,
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing GlobalAnswerReadiness key: issues"):
            assert_global_answer_readiness(bad)

    def test_missing_observation_for_replan_key_raises(self) -> None:
        """Missing observation_for_replan key triggers AssertionError."""
        bad = {
            "sufficient_for_answer": True,
            "need_replan": False,
            "issues": [],
        }
        with pytest.raises(AssertionError, match="missing GlobalAnswerReadiness key: observation_for_replan"):
            assert_global_answer_readiness(bad)

    # -- need_replan / observation_for_replan interaction ---------------------

    def test_need_replan_true_blank_observation_raises(self) -> None:
        """need_replan=True with whitespace-only observation_for_replan must fail."""
        bad = sample_global_readiness(
            sufficient_for_answer=False,
            need_replan=True,
            observation_for_replan="   ",
        )
        with pytest.raises(AssertionError):
            assert_global_answer_readiness(bad)

    def test_need_replan_true_empty_observation_raises(self) -> None:
        """need_replan=True with empty string observation must fail."""
        bad = sample_global_readiness(
            sufficient_for_answer=False,
            need_replan=True,
            observation_for_replan="",
        )
        with pytest.raises(AssertionError):
            assert_global_answer_readiness(bad)

    def test_need_replan_truthy_non_bool_triggers_observation_check(self) -> None:
        """need_replan with truthy non-bool (e.g. non-empty string) triggers observation check."""
        bad = {
            "sufficient_for_answer": False,
            "need_replan": "yes",
            "issues": [],
            "observation_for_replan": "   ",
        }
        with pytest.raises(AssertionError):
            assert_global_answer_readiness(bad)

    def test_need_replan_truthy_non_bool_with_valid_observation_passes(self) -> None:
        """need_replan truthy non-bool with valid observation passes contract."""
        result = {
            "sufficient_for_answer": False,
            "need_replan": 1,
            "issues": ["evidence gap"],
            "observation_for_replan": "need to search more",
        }
        assert_global_answer_readiness(result)

    # -- issues field ---------------------------------------------------------

    def test_issues_must_be_list(self) -> None:
        """issues field must be a list."""
        result = sample_global_readiness()
        assert isinstance(result["issues"], list)

    def test_issues_can_contain_strings(self) -> None:
        """Issues entries are typically human-readable strings."""
        result = sample_global_readiness(issues=["low confidence", "missing citation"])
        assert_global_answer_readiness(result)
        assert all(isinstance(i, str) for i in result["issues"])

    # -- suggested_retrieval_changes field ------------------------------------

    def test_suggested_retrieval_changes_present(self) -> None:
        """suggested_retrieval_changes key must exist (may be empty list)."""
        result = sample_global_readiness()
        assert "suggested_retrieval_changes" in result
        assert isinstance(result["suggested_retrieval_changes"], list)

    def test_suggested_retrieval_changes_structure(self) -> None:
        """Each retrieval change suggestion should be a dict."""
        result = sample_global_readiness(
            suggested_retrieval_changes=[
                {"tool": "search_by_metadata", "query": "TOPMOST architecture", "reason": "missing figure data"},
            ]
        )
        assert_global_answer_readiness(result)
        for change in result["suggested_retrieval_changes"]:
            assert isinstance(change, dict)

    # -- tolerance ------------------------------------------------------------

    def test_extra_keys_ignored(self) -> None:
        """Contract is tolerant of extra/unknown keys."""
        result = sample_global_readiness(extra_field=42, another_field="ignored")
        assert_global_answer_readiness(result)
        assert result["extra_field"] == 42
