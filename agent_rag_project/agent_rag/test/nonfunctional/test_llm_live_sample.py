"""阶段 10.4 — 真实 LLM。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.llm_live]

def test_live():
    pytest.skip("local only")
