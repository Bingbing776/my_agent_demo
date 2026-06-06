"""阶段 2.2.2 — Generator.summarize_mcp_result。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_concat_text_only(generator, mock_mcp_raw_text, mock_mcp_raw_multimodal, mock_mcp_raw_error):
    s = generator.summarize_mcp_result(mock_mcp_raw_text); assert "hello" in s

def test_error_prefix(generator, mock_mcp_raw_text, mock_mcp_raw_multimodal, mock_mcp_raw_error):
    s = generator.summarize_mcp_result(mock_mcp_raw_error); assert "[error]" in s

def test_image_placeholder(generator, mock_mcp_raw_text, mock_mcp_raw_multimodal, mock_mcp_raw_error):
    s = generator.summarize_mcp_result(mock_mcp_raw_multimodal); assert "图" in s or "image" in s.lower()
