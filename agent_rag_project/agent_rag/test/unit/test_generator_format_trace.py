"""阶段 2.2.3 — Generator._format_trace。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_empty_placeholder(generator):
    s = generator._format_trace([]); assert s

def test_formats_tool_and_summary(generator):
    s = generator._format_trace([{"tool_name": "t", "summary": "ok"}]); assert "t" in s and "ok" in s
