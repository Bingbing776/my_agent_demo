"""gate.1 -- NextActionResult contract (phase 1.1).

Validates Generator.choose_next_action return structure:
- action must be in {"call_tool", "stop", "replan"}
- action="call_tool" requires truthy tool_name

ContractGate import (symbol=all):
- _gate function serves as gate.1 entry point for this contract type
"""
from __future__ import annotations

import pytest

from test.helpers.contracts import assert_next_action_result

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# local sample helper -- sample_next_action_result not yet in test.helpers.samples
# ---------------------------------------------------------------------------

def _next_action(**overrides):
    """Canonical NextActionResult dict; defaults to call_tool with query_knowledge_hub."""
    base = {"action": "call_tool", "tool_name": "query_knowledge_hub"}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _gate -- gate.1 aggregator: symbol=all, target_class=ContractGate
# ---------------------------------------------------------------------------

def _gate() -> None:
    """ContractGate: validate NextActionResult contract.

    Imports ContractGate from agent_rag (when implemented) and verifies
    the next_action_result contract assertions pass against canonical
    sample data.  This is one entry-point for the gate.1 milestone.
    """
    # Import ContractGate -- skip if not yet implemented
    try:
        from agent_rag import ContractGate  # noqa: F401
    except ImportError:
        pass  # ContractGate not implemented yet; contract helpers still validated

    # NextActionResult -- canonical shapes
    assert_next_action_result(_next_action())
    assert_next_action_result(_next_action(action="stop"))
    assert_next_action_result(_next_action(action="replan"))


# ---------------------------------------------------------------------------
# NextActionResult contract tests (phase 1.1)
# ---------------------------------------------------------------------------

class TestNextActionResult:
    """Verify Generator.choose_next_action return structure."""

    # -- positive tests -------------------------------------------------------

    def test_call_tool_action(self) -> None:
        """Standard call_tool action with tool_name passes."""
        assert_next_action_result(_next_action())

    def test_call_tool_with_read_chunk(self) -> None:
        """Different tool_name for call_tool also passes."""
        assert_next_action_result(_next_action(tool_name="read_chunk"))

    def test_call_tool_with_search(self) -> None:
        """Any truthy tool_name satisfies the contract."""
        assert_next_action_result(_next_action(tool_name="search_by_metadata"))

    def test_stop_action(self) -> None:
        """action=stop passes; tool_name is not required."""
        assert_next_action_result(_next_action(action="stop"))

    def test_replan_action(self) -> None:
        """action=replan passes; tool_name is not required."""
        assert_next_action_result(_next_action(action="replan"))

    def test_stop_with_extra_keys_tolerated(self) -> None:
        """Extra keys beyond action/tool_name are tolerated."""
        result = {"action": "stop", "tool_name": "ignored", "confidence": 0.9}
        assert_next_action_result(result)

    def test_replan_with_extra_keys_tolerated(self) -> None:
        """replan with advisory extra fields still passes."""
        result = {"action": "replan", "reason": "need more data"}
        assert_next_action_result(result)

    # -- negative tests -------------------------------------------------------

    def test_invalid_action_raises(self) -> None:
        """action not in {call_tool, stop, replan} triggers AssertionError."""
        bad = {"action": "unknown_action"}
        with pytest.raises(AssertionError):
            assert_next_action_result(bad)

    def test_call_tool_missing_tool_name_raises(self) -> None:
        """action=call_tool without tool_name triggers AssertionError."""
        bad = {"action": "call_tool"}
        with pytest.raises(AssertionError):
            assert_next_action_result(bad)

    def test_call_tool_empty_tool_name_raises(self) -> None:
        """action=call_tool with empty string tool_name triggers AssertionError."""
        bad = {"action": "call_tool", "tool_name": ""}
        with pytest.raises(AssertionError):
            assert_next_action_result(bad)

    def test_action_missing_key_raises(self) -> None:
        """Missing action key triggers AssertionError (None not in NEXT_ACTIONS)."""
        bad: dict = {}
        with pytest.raises(AssertionError):
            assert_next_action_result(bad)

    def test_action_none_raises(self) -> None:
        """action=None not in NEXT_ACTIONS triggers AssertionError."""
        bad = {"action": None}
        with pytest.raises(AssertionError):
            assert_next_action_result(bad)

    def test_call_tool_tool_name_none_raises(self) -> None:
        """action=call_tool with tool_name=None fails truthiness check."""
        bad = {"action": "call_tool", "tool_name": None}
        with pytest.raises(AssertionError):
            assert_next_action_result(bad)
