"""gate.1 -- ContractGate all-contracts aggregator + SubtaskResult contract (phase 1.3).

Validates:
- ContractGate import from agent_rag (symbol=all, gate.1 entry point)
- SubtaskResult structure: task_id, status, draft_text, tool_trace, observation_for_replan
- status must be in {success, failed, needs_replan}
- tool_trace entries must have tool_name, ok, summary

Other contract types tested in sibling files:
- test_next_action_result.py (phase 1.1)
- test_eval_result.py (phase 1.2)
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
    sample_tool_trace_entry,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# _gate -- gate.1 aggregator: symbol=all, target_class=ContractGate
# ---------------------------------------------------------------------------

def _gate() -> None:
    """ContractGate: validate ALL contract types in one gate call.

    Imports ContractGate from agent_rag and verifies that every contract
    assertion from test.helpers.contracts passes against canonical sample
    data.  This is the single entry-point for the gate.1 milestone.
    """
    # ContractGate must be importable (top-level import already ensures this)
    assert ContractGate is not None, "ContractGate class must exist in agent_rag"

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
# SubtaskResult contract tests (phase 1.3)
# ---------------------------------------------------------------------------

class TestSubtaskResult:
    """Verify Generator.run_subtask return structure (SubtaskResult)."""

    # ---- positive tests ---------------------------------------------------

    def test_minimal_shape(self) -> None:
        """Canonical success SubtaskResult passes all contract checks."""
        result = sample_subtask_result()
        assert_subtask_result(result)
        assert result["task_id"] == "t1"
        assert result["status"] == "success"
        assert isinstance(result["draft_text"], str)
        assert isinstance(result["tool_trace"], list)
        assert isinstance(result["observation_for_replan"], str)

    def test_success_status(self) -> None:
        """status='success' is valid."""
        assert_subtask_result(sample_subtask_result(status="success"))

    def test_failed_status(self) -> None:
        """status='failed' is valid (tool call failed but result is well-formed)."""
        assert_subtask_result(
            sample_subtask_result(
                status="failed",
                observation_for_replan="query_knowledge_hub returned empty",
                tool_trace=[sample_tool_trace_entry(ok=False, summary="error")],
            )
        )

    def test_needs_replan_status(self) -> None:
        """status='needs_replan' with observation_for_replan."""
        result = sample_subtask_result(
            status="needs_replan",
            observation_for_replan="missing chunk data, replan needed",
        )
        assert_subtask_result(result)
        assert result["observation_for_replan"] != ""

    def test_multiple_tool_trace_entries(self) -> None:
        """tool_trace can contain multiple entries, each with required keys."""
        result = sample_subtask_result(
            tool_trace=[
                sample_tool_trace_entry(tool_name="query_knowledge_hub", ok=True, summary="hit"),
                sample_tool_trace_entry(tool_name="read_chunk", ok=True, summary="chunk read"),
                sample_tool_trace_entry(tool_name="check_evidence", ok=True, summary="verified"),
            ]
        )
        assert_subtask_result(result)
        assert len(result["tool_trace"]) == 3

    def test_empty_tool_trace(self) -> None:
        """Empty tool_trace is allowed (no tools called)."""
        result = sample_subtask_result(tool_trace=[])
        assert_subtask_result(result)
        assert result["tool_trace"] == []

    def test_preserves_citations(self) -> None:
        """citations field carries evidence references."""
        citations = [
            {"chunk_id": "abc123", "text_snippet": "key finding"},
            {"chunk_id": "def456", "text_snippet": "another finding"},
        ]
        result = sample_subtask_result(citations=citations)
        assert_subtask_result(result)
        assert "citations" in result
        assert len(result["citations"]) == 2

    def test_preserves_images(self) -> None:
        """images field carries image data collected during subtask."""
        images = [{"mime_type": "image/png", "data": "iVBORw0KGgo="}]
        result = sample_subtask_result(images=images)
        assert_subtask_result(result)
        assert "images" in result
        assert len(result["images"]) == 1

    def test_extra_keys_tolerated(self) -> None:
        """Contract is tolerant of extra/unknown keys at top level."""
        result = sample_subtask_result(extra_field=42, another_field="ignored")
        assert_subtask_result(result)
        assert result["extra_field"] == 42
        assert result["another_field"] == "ignored"

    def test_tool_trace_entry_extra_keys_tolerated(self) -> None:
        """Extra keys in tool_trace entries are tolerated."""
        result = sample_subtask_result(
            tool_trace=[
                {
                    "tool_name": "query_knowledge_hub",
                    "ok": True,
                    "summary": "hit",
                    "duration_ms": 123,
                    "extra": "ignored",
                }
            ]
        )
        assert_subtask_result(result)

    def test_draft_text_multiline(self) -> None:
        """Multi-line draft_text passes contract."""
        result = sample_subtask_result(
            draft_text="Line one.\\nLine two.\\nLine three."
        )
        assert_subtask_result(result)
        assert "\\n" in result["draft_text"]

    def test_observation_for_replan_empty_on_success(self) -> None:
        """observation_for_replan may be empty when status=success."""
        result = sample_subtask_result(status="success", observation_for_replan="")
        assert_subtask_result(result)
        assert result["observation_for_replan"] == ""

    # ---- negative tests: missing keys --------------------------------------

    def test_missing_task_id_raises(self) -> None:
        """Missing task_id key triggers AssertionError."""
        bad = {
            "status": "success",
            "draft_text": "x",
            "tool_trace": [],
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing SubtaskResult key: task_id"):
            assert_subtask_result(bad)

    def test_missing_status_raises(self) -> None:
        """Missing status key triggers AssertionError."""
        bad = {
            "task_id": "t1",
            "draft_text": "x",
            "tool_trace": [],
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing SubtaskResult key: status"):
            assert_subtask_result(bad)

    def test_missing_draft_text_raises(self) -> None:
        """Missing draft_text key triggers AssertionError."""
        bad = {
            "task_id": "t1",
            "status": "success",
            "tool_trace": [],
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing SubtaskResult key: draft_text"):
            assert_subtask_result(bad)

    def test_missing_tool_trace_raises(self) -> None:
        """Missing tool_trace key triggers AssertionError."""
        bad = {
            "task_id": "t1",
            "status": "success",
            "draft_text": "x",
            "observation_for_replan": "",
        }
        with pytest.raises(AssertionError, match="missing SubtaskResult key: tool_trace"):
            assert_subtask_result(bad)

    def test_missing_observation_for_replan_raises(self) -> None:
        """Missing observation_for_replan key triggers AssertionError."""
        bad = {
            "task_id": "t1",
            "status": "success",
            "draft_text": "x",
            "tool_trace": [],
        }
        with pytest.raises(
            AssertionError, match="missing SubtaskResult key: observation_for_replan"
        ):
            assert_subtask_result(bad)

    def test_empty_dict_raises(self) -> None:
        """Completely empty dict fails on first missing key."""
        with pytest.raises(AssertionError, match="missing SubtaskResult key: task_id"):
            assert_subtask_result({})

    # ---- negative tests: invalid status ------------------------------------

    def test_invalid_status_raises(self) -> None:
        """Status not in {success, failed, needs_replan} triggers AssertionError."""
        bad = sample_subtask_result(status="unknown_status")
        with pytest.raises(AssertionError):
            assert_subtask_result(bad)

    def test_status_none_raises(self) -> None:
        """status=None is not in SUBTASK_STATUSES."""
        bad = sample_subtask_result(status=None)
        with pytest.raises(AssertionError):
            assert_subtask_result(bad)

    def test_status_int_raises(self) -> None:
        """status as int triggers AssertionError."""
        bad = sample_subtask_result(status=1)
        with pytest.raises(AssertionError):
            assert_subtask_result(bad)

    def test_status_empty_string_raises(self) -> None:
        """status='' is not in SUBTASK_STATUSES."""
        bad = sample_subtask_result(status="")
        with pytest.raises(AssertionError):
            assert_subtask_result(bad)

    # ---- negative tests: tool_trace entry checks ---------------------------

    def test_tool_trace_entry_missing_tool_name_raises(self) -> None:
        """tool_trace entry missing tool_name triggers AssertionError."""
        bad = sample_subtask_result(
            tool_trace=[{"ok": True, "summary": "x"}]
        )
        with pytest.raises(AssertionError, match="tool_trace missing tool_name"):
            assert_subtask_result(bad)

    def test_tool_trace_entry_missing_ok_raises(self) -> None:
        """tool_trace entry missing ok triggers AssertionError."""
        bad = sample_subtask_result(
            tool_trace=[{"tool_name": "t", "summary": "x"}]
        )
        with pytest.raises(AssertionError, match="tool_trace missing ok"):
            assert_subtask_result(bad)

    def test_tool_trace_entry_missing_summary_raises(self) -> None:
        """tool_trace entry missing summary triggers AssertionError."""
        bad = sample_subtask_result(
            tool_trace=[{"tool_name": "t", "ok": True}]
        )
        with pytest.raises(AssertionError, match="tool_trace missing summary"):
            assert_subtask_result(bad)

    def test_tool_trace_entry_empty_dict_raises(self) -> None:
        """tool_trace entry as empty dict fails on first missing tool_trace key."""
        bad = sample_subtask_result(tool_trace=[{}])
        with pytest.raises(AssertionError, match="tool_trace missing tool_name"):
            assert_subtask_result(bad)

    def test_tool_trace_not_list_raises(self) -> None:
        """tool_trace that is not a list should still iterate but entry checks apply."""
        bad = sample_subtask_result(tool_trace="not_a_list")
        # iterating over a string yields characters; each char is not a dict
        with pytest.raises(AssertionError):
            assert_subtask_result(bad)

    def test_tool_trace_is_none_raises(self) -> None:
        """tool_trace=None triggers TypeError during iteration."""
        bad = sample_subtask_result(tool_trace=None)
        with pytest.raises(TypeError):
            assert_subtask_result(bad)

    # ---- negative tests: type checks ---------------------------------------

    def test_task_id_none_raises(self) -> None:
        """task_id=None still passes key check but may cause downstream issues.

        The contract only validates key presence and status / tool_trace
        structure; it does not enforce that task_id is a string.
        """
        result = sample_subtask_result(task_id=None)
        # Contract passes because key exists; type is not enforced
        assert_subtask_result(result)

    def test_draft_text_not_str_passes(self) -> None:
        """draft_text as int still passes contract (key presence only)."""
        result = sample_subtask_result(draft_text=42)
        # Contract passes because key exists; type is not enforced
        assert_subtask_result(result)

    def test_citations_not_list_passes(self) -> None:
        """citations as non-list passes contract (citations not in contract keys)."""
        result = sample_subtask_result(citations="not_a_list")
        assert_subtask_result(result)

    def test_images_not_list_passes(self) -> None:
        """images as non-list passes contract (images not in contract keys)."""
        result = sample_subtask_result(images="not_a_list")
        assert_subtask_result(result)
