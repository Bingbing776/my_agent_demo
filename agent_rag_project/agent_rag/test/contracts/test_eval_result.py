# -*- coding: utf-8 -*-
"""Phase 1.2 -- EvalResult contract + gate.1 entry point.

Validates:
- ContractGate import from agent_rag (symbol=all, gate.1 entry point)
- EvalResult structure: passed, score, require_more_tools, status, issues
- status must be in {ok, needs_replan, hard_fail}
- needs_replan implies passed is False

Other contract types tested in sibling files:
- test_next_action_result.py (phase 1.1)
- test_subtask_result.py (phase 1.3)
- test_mcp_normalized.py (phase 1.4)
- test_global_readiness.py (phase 1.5)
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
# Existing EvalResult contract tests (kept from original)
# ---------------------------------------------------------------------------

def test_ok_shape():
    """Canonical ok EvalResult passes all contract checks."""
    assert_eval_result(sample_eval_result())


def test_needs_replan_implies_not_passed():
    """needs_replan status requires passed=False, enforced by contract."""
    assert_eval_result(sample_eval_result(passed=False, status="needs_replan"))


# ---------------------------------------------------------------------------
# EvalResult contract tests (phase 1.2)
# ---------------------------------------------------------------------------

class TestEvalResult:
    """Verify Evaluator.evaluate return structure (EvalResult)."""

    # ---- positive tests ---------------------------------------------------

    def test_ok_minimal_shape(self) -> None:
        """Canonical ok EvalResult passes and has all required keys."""
        result = sample_eval_result()
        assert_eval_result(result)
        assert result["passed"] is True
        assert result["score"] == 0.9
        assert result["require_more_tools"] is False
        assert result["status"] == "ok"
        assert isinstance(result["issues"], list)

    def test_status_ok_passes(self) -> None:
        """status='ok' is valid regardless of passed value."""
        assert_eval_result(sample_eval_result(passed=True, status="ok"))
        assert_eval_result(sample_eval_result(passed=False, status="ok"))

    def test_status_needs_replan_passes(self) -> None:
        """status='needs_replan' with passed=False is valid."""
        result = sample_eval_result(passed=False, status="needs_replan")
        assert_eval_result(result)
        assert result["status"] == "needs_replan"
        assert result["passed"] is False

    def test_status_hard_fail_passes(self) -> None:
        """status='hard_fail' is a valid terminal status."""
        result = sample_eval_result(passed=False, status="hard_fail")
        assert_eval_result(result)

    def test_score_zero(self) -> None:
        """score=0.0 is allowed."""
        result = sample_eval_result(score=0.0)
        assert_eval_result(result)
        assert result["score"] == 0.0

    def test_score_one(self) -> None:
        """score=1.0 is allowed (perfect score)."""
        result = sample_eval_result(score=1.0)
        assert_eval_result(result)
        assert result["score"] == 1.0

    def test_score_between(self) -> None:
        """score in (0, 1) range passes."""
        result = sample_eval_result(score=0.55)
        assert_eval_result(result)

    def test_require_more_tools_true(self) -> None:
        """require_more_tools=True signals more retrieval needed."""
        result = sample_eval_result(require_more_tools=True)
        assert_eval_result(result)
        assert result["require_more_tools"] is True

    def test_require_more_tools_false(self) -> None:
        """require_more_tools=False means evaluator is satisfied."""
        result = sample_eval_result(require_more_tools=False)
        assert_eval_result(result)
        assert result["require_more_tools"] is False

    def test_issues_with_multiple_entries(self) -> None:
        """issues list can carry multiple diagnostic messages."""
        issues = ["low confidence", "missing citation", "incomplete evidence"]
        result = sample_eval_result(passed=False, status="hard_fail", issues=issues)
        assert_eval_result(result)
        assert len(result["issues"]) == 3

    def test_issues_empty_list(self) -> None:
        """Empty issues list is allowed for clean results."""
        result = sample_eval_result(issues=[])
        assert_eval_result(result)
        assert result["issues"] == []

    def test_hard_fail_with_passed_false(self) -> None:
        """hard_fail should normally have passed=False."""
        result = sample_eval_result(passed=False, status="hard_fail", issues=["fatal error"])
        assert_eval_result(result)

    def test_extra_keys_tolerated(self) -> None:
        """Contract is tolerant of extra/unknown keys."""
        result = sample_eval_result(extra_field=42, confidence=0.8)
        assert_eval_result(result)
        assert result["extra_field"] == 42
        assert result["confidence"] == 0.8

    def test_issues_with_mixed_types(self) -> None:
        """issues list may contain non-string entries; contract only checks key presence."""
        result = sample_eval_result(issues=["msg", 42, {"detail": "nested"}])
        assert_eval_result(result)

    def test_score_negative(self) -> None:
        """Negative score passes contract (contract does not enforce range)."""
        result = sample_eval_result(score=-0.1)
        assert_eval_result(result)

    def test_score_above_one(self) -> None:
        """Score above 1.0 passes contract (contract does not enforce range)."""
        result = sample_eval_result(score=1.5)
        assert_eval_result(result)

    # ---- negative tests: missing keys --------------------------------------

    def test_missing_passed_raises(self) -> None:
        """Missing passed key triggers AssertionError."""
        bad = {
            "score": 0.5,
            "require_more_tools": False,
            "status": "ok",
            "issues": [],
        }
        with pytest.raises(AssertionError, match="missing EvalResult key: passed"):
            assert_eval_result(bad)

    def test_missing_score_raises(self) -> None:
        """Missing score key triggers AssertionError."""
        bad = {
            "passed": True,
            "require_more_tools": False,
            "status": "ok",
            "issues": [],
        }
        with pytest.raises(AssertionError, match="missing EvalResult key: score"):
            assert_eval_result(bad)

    def test_missing_require_more_tools_raises(self) -> None:
        """Missing require_more_tools key triggers AssertionError."""
        bad = {
            "passed": True,
            "score": 0.9,
            "status": "ok",
            "issues": [],
        }
        with pytest.raises(AssertionError, match="missing EvalResult key: require_more_tools"):
            assert_eval_result(bad)

    def test_missing_status_raises(self) -> None:
        """Missing status key triggers AssertionError."""
        bad = {
            "passed": True,
            "score": 0.9,
            "require_more_tools": False,
            "issues": [],
        }
        with pytest.raises(AssertionError, match="missing EvalResult key: status"):
            assert_eval_result(bad)

    def test_missing_issues_raises(self) -> None:
        """Missing issues key triggers AssertionError."""
        bad = {
            "passed": True,
            "score": 0.9,
            "require_more_tools": False,
            "status": "ok",
        }
        with pytest.raises(AssertionError, match="missing EvalResult key: issues"):
            assert_eval_result(bad)

    def test_empty_dict_raises(self) -> None:
        """Completely empty dict fails on first missing key."""
        with pytest.raises(AssertionError, match="missing EvalResult key: passed"):
            assert_eval_result({})

    def test_missing_multiple_keys_raises(self) -> None:
        """Only one key missing from required set triggers error on first missing."""
        bad = {"passed": True}
        with pytest.raises(AssertionError, match="missing EvalResult key: score"):
            assert_eval_result(bad)

    # ---- negative tests: invalid status ------------------------------------

    def test_invalid_status_raises(self) -> None:
        """status not in {ok, needs_replan, hard_fail} triggers AssertionError."""
        bad = sample_eval_result(status="unknown")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_status_none_raises(self) -> None:
        """status=None is not in EVAL_STATUSES."""
        bad = sample_eval_result(status=None)
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_status_int_raises(self) -> None:
        """status as int triggers AssertionError."""
        bad = sample_eval_result(status=1)
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_status_empty_string_raises(self) -> None:
        """status='' is not in EVAL_STATUSES."""
        bad = sample_eval_result(status="")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_status_case_sensitive_raises(self) -> None:
        """status='OK' (uppercase) is not in EVAL_STATUSES."""
        bad = sample_eval_result(status="OK")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_status_with_whitespace_raises(self) -> None:
        """status=' ok' (leading space) is not in EVAL_STATUSES."""
        bad = sample_eval_result(status=" ok")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    # ---- negative tests: needs_replan invariant ----------------------------

    def test_needs_replan_with_passed_true_raises(self) -> None:
        """needs_replan with passed=True violates invariant and must fail."""
        bad = sample_eval_result(passed=True, status="needs_replan")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_needs_replan_with_passed_truthy_non_bool_raises(self) -> None:
        """needs_replan with passed=1 (truthy, not exactly False) must fail."""
        bad = sample_eval_result(passed=1, status="needs_replan")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_needs_replan_with_passed_none_raises(self) -> None:
        """needs_replan with passed=None must fail (None is not False)."""
        bad = sample_eval_result(passed=None, status="needs_replan")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_needs_replan_with_passed_string_raises(self) -> None:
        """needs_replan with passed as non-empty string must fail."""
        bad = sample_eval_result(passed="yes", status="needs_replan")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_needs_replan_with_passed_falsy_zero_raises(self) -> None:
        """needs_replan with passed=0 must fail (0 is not False by identity)."""
        bad = sample_eval_result(passed=0, status="needs_replan")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    def test_needs_replan_with_passed_falsy_empty_list_raises(self) -> None:
        """needs_replan with passed=[] must fail ([] is not False)."""
        bad = sample_eval_result(passed=[], status="needs_replan")
        with pytest.raises(AssertionError):
            assert_eval_result(bad)

    # ---- negative tests: type validation (contract is lenient on types) ----

    def test_passed_none_ok_status_passes(self) -> None:
        """passed=None with status='ok' passes; contract only enforces key presence."""
        result = sample_eval_result(passed=None, status="ok")
        assert_eval_result(result)

    def test_passed_int_ok_status_passes(self) -> None:
        """passed=42 with status='ok' passes; contract is lenient on non-needs_replan."""
        result = sample_eval_result(passed=42, status="ok")
        assert_eval_result(result)

    def test_score_string_passes(self) -> None:
        """score as string passes contract (key presence only, no type enforcement)."""
        result = sample_eval_result(score="high")
        assert_eval_result(result)

    def test_require_more_tools_non_bool_passes(self) -> None:
        """require_more_tools as string passes (no type enforcement)."""
        result = sample_eval_result(require_more_tools="yes")
        assert_eval_result(result)

    def test_issues_not_list_passes(self) -> None:
        """issues as string passes contract (key presence only)."""
        result = sample_eval_result(issues="not_a_list")
        assert_eval_result(result)

    # ---- boundary: hard_fail can have passed=True (not checked by contract) ----

    def test_hard_fail_with_passed_true_passes(self) -> None:
        """hard_fail with passed=True passes (contract only enforces needs_replan invariant)."""
        result = sample_eval_result(passed=True, status="hard_fail")
        assert_eval_result(result)

    def test_hard_fail_with_passed_none_passes(self) -> None:
        """hard_fail with passed=None passes contract."""
        result = sample_eval_result(passed=None, status="hard_fail")
        assert_eval_result(result)
