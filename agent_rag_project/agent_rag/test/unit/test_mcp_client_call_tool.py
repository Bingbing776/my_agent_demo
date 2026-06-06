"""Phase 4.2 -- McpClient.call_tool. See docs/test_outline.md"""
import asyncio
import base64
import pytest
from unittest.mock import MagicMock

from agent_rag.mcp.mcp_client import McpClient

pytestmark = [pytest.mark.unit]


def test_normalized_shape(mcp_client, mock_mcp_session):
    """call_tool must normalize the underlying session result into a dict with
    content (list of {type, ...}), isError (bool), and optionally
    structuredContent / images."""

    # -- Scenario 1: default mock (text-only success) --
    result = asyncio.run(mcp_client.call_tool("search", {"q": "test"}))

    assert isinstance(result, dict), "result must be a dict"
    assert "content" in result, "must have content key"
    assert "isError" in result, "must have isError key"
    assert isinstance(result["content"], list), "content must be a list"
    assert isinstance(result["isError"], bool), "isError must be bool"

    # Default mock returns isError=False
    assert result["isError"] is False

    # structuredContent is None in default mock -> should be absent
    assert "structuredContent" not in result, (
        "structuredContent must be absent when underlying result has None"
    )

    # No image blocks in default mock -> images absent
    assert "images" not in result, "images must be absent when no image blocks"

    # Each content item must be a dict with a "type" key
    for idx, item in enumerate(result["content"]):
        assert isinstance(item, dict), f"content[{idx}] must be a dict"
        assert "type" in item, f"content[{idx}] must have 'type'"
        assert item["type"] in ("text", "image"), (
            f"content[{idx}].type must be 'text' or 'image', got {item['type']!r}"
        )

    # Default mock has one text block with text="ok"
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "ok"

    # -- Scenario 2: error result (isError=True) --
    err_block = MagicMock()
    err_block.model_dump = lambda: {"type": "text", "text": "tool failed"}
    mock_mcp_session.call_tool.return_value = MagicMock(
        content=[err_block],
        isError=True,
        structuredContent=None,
    )
    result_err = asyncio.run(mcp_client.call_tool("bad_tool", {}))
    assert result_err["isError"] is True, "isError must be True for error result"
    assert result_err["content"][0]["text"] == "tool failed"
    assert "images" not in result_err, "images must be absent in error result"
    assert "structuredContent" not in result_err, (
        "structuredContent must be absent when None in error result"
    )

    # -- Scenario 3: multimodal result with image blocks --
    png_data = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    txt_block = MagicMock()
    txt_block.model_dump = lambda: {"type": "text", "text": "see figure"}
    img_block = MagicMock()
    img_block.model_dump = lambda: {"type": "image", "data": png_data, "mimeType": "image/png"}
    mock_mcp_session.call_tool.return_value = MagicMock(
        content=[txt_block, img_block],
        isError=False,
        structuredContent=None,
    )
    result_mm = asyncio.run(mcp_client.call_tool("get_figure", {}))
    assert "images" in result_mm, "images key must be present for multimodal result"
    assert len(result_mm["images"]) == 1
    assert result_mm["images"][0]["data"] == png_data
    assert result_mm["images"][0]["mime_type"] == "image/png"
    assert result_mm["images"][0]["index"] == 1, "image index must match position in content"
    assert len(result_mm["content"]) == 2
    assert result_mm["content"][0]["type"] == "text"
    assert result_mm["content"][1]["type"] == "image"
    assert result_mm["content"][1]["data"] == png_data
    assert result_mm["content"][1]["mimeType"] == "image/png"

    # -- Scenario 4: structuredContent present (non-None) --
    txt2 = MagicMock()
    txt2.model_dump = lambda: {"type": "text", "text": "hello"}
    sc = {"citations": [{"text_snippet": "cite1", "chunk_id": "c1"}]}
    mock_mcp_session.call_tool.return_value = MagicMock(
        content=[txt2],
        isError=False,
        structuredContent=sc,
    )
    result_sc = asyncio.run(mcp_client.call_tool("search2", {}))
    assert "structuredContent" in result_sc, (
        "structuredContent must be present when underlying result has it"
    )
    assert result_sc["structuredContent"] == sc
    assert result_sc["structuredContent"]["citations"][0]["text_snippet"] == "cite1"
    assert result_sc["structuredContent"]["citations"][0]["chunk_id"] == "c1"
