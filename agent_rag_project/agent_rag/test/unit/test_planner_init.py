"""Phase 3.11 — PlannerAgent.__init__. See docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]


def test_constructs(planner_agent):
    """PlannerAgent is constructed with all required internal state."""
    assert planner_agent is not None

    # config must be stored as a dict (default {} when None passed)
    assert hasattr(planner_agent, '_config')
    assert isinstance(planner_agent._config, dict)

    # LLM must be created and cached during __init__
    assert hasattr(planner_agent, '_llm')
    assert planner_agent._llm is not None

    # routing skill path attribute must exist
    assert hasattr(planner_agent, '_routing_skill_path')

    # routing hint cache must be initialized to None
    assert hasattr(planner_agent, '_routing_hint_cache')
    assert planner_agent._routing_hint_cache is None
