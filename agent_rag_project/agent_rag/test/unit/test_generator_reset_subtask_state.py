"""阶段 7.1 — Generator.reset_subtask_state。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_clears(generator):
    generator.reset_subtask_state(); assert generator._inner_trace == []
