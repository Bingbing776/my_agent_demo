"""阶段 2.2.1 — Generator._collect_images_from_raw。见 docs/test_outline.md"""
import pytest

pytestmark = [pytest.mark.unit]

def test_from_content(generator, mock_mcp_raw_text, mock_mcp_raw_multimodal, mock_mcp_raw_error):
    imgs = generator._collect_images_from_raw(mock_mcp_raw_multimodal); assert len(imgs) >= 1

def test_skip_empty_data(generator):
    raw = {"content": [{"type": "image", "data": "", "mimeType": "image/png"}]}; assert generator._collect_images_from_raw(raw) == []
