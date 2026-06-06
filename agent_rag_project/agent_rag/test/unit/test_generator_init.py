"""阶段 3.13 — Generator.__init__。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_inner_state(generator):
    assert hasattr(generator, "_inner_trace") or hasattr(generator, "reset_subtask_state")
