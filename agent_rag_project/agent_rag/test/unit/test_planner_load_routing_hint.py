import pytest

from agent_rag.agents.planner import PlannerAgent

pytestmark = [pytest.mark.unit]


def test_cache_second_call(planner_agent):
    """load_routing_hint caches its result; second call returns same value."""

    # Cache must start as None per __init__
    assert planner_agent._routing_hint_cache is None, (
        "_routing_hint_cache must be None before first call"
    )

    h1 = planner_agent.load_routing_hint()

    # First call must return a string
    assert isinstance(h1, str), f"Expected str, got {type(h1)}"

    # Capture cache state after first call.
    # If routing_skill_path was valid and the file was read, cache is populated.
    # If path was empty or file missing, cache may remain None (spec step 2 / read failure).
    cached = planner_agent._routing_hint_cache

    # When cache was populated, it must equal the first call's return value
    if cached is not None:
        assert cached == h1, (
            "After first call, _routing_hint_cache must equal the returned value"
        )

    h2 = planner_agent.load_routing_hint()

    # Second call must also return a string
    assert isinstance(h2, str), f"Expected str, got {type(h2)}"

    # Second call must return the same value as the first
    assert h2 == h1, "Second call must return cached value identical to first"

    # When cache was populated (file successfully read), the second call
    # must return the exact cached object, proving the cache short-circuit was hit.
    if cached is not None:
        assert h2 is cached, (
            "Second call must return the cached object itself (identity check)"
        )
