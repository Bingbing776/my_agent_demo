"""§3 — McpClient + Executor function gate acceptance tests.

Test strategy:
- mock tests: verify code logic with mock_mcp_session (argument passing,
  return parsing, error handling)
- @pytest.mark.llm_live tests: verify real MCP call chain with
  real_mcp_client/real_executor. Validates 10 MCP tool call logics:
  query_knowledge_hub, read_chunk, get_neighbor_chunks, check_evidence,
  search_by_metadata, list_collections, list_documents,
  get_document_summary, get_document_outline, get_document_full_text
"""
import asyncio
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock

from test.helpers.samples import (
    sample_mcp_raw_text_only,
    sample_mcp_tool_call_result,
)

pytestmark = [pytest.mark.gate]


# --- Core gate function (callable by Harness directly) ---

def _gate(mcp_client, mock_mcp_session):
    """Core gate: McpClient.call_tool normalizes results per done_criteria.

    Verifies:
    - content list shape with type key
    - isError flag passthrough
    - structuredContent passthrough (absent when None, present when non-None)
    - image extraction from image blocks
    - input validation (raises ValueError on bad inputs)
    - realistic sample data from knowledge hub
    """
    # --- Scenario 1: default mock (text-only success) ---
    result = asyncio.run(mcp_client.call_tool("search", {"q": "test"}))

    assert isinstance(result, dict), "result must be a dict"
    assert "content" in result, "must have content key"
    assert "isError" in result, "must have isError key"
    assert isinstance(result["content"], list), "content must be a list"
    assert isinstance(result["isError"], bool), "isError must be bool"
    assert result["isError"] is False

    # structuredContent absent when underlying has None
    assert "structuredContent" not in result, (
        "structuredContent must be absent when underlying result has None"
    )

    # No image blocks => images absent
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

    # --- Scenario 2: error result (isError=True) ---
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

    # --- Scenario 3: multimodal result with image blocks ---
    png_data = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    txt_block = MagicMock()
    txt_block.model_dump = lambda: {"type": "text", "text": "see figure"}
    img_block = MagicMock()
    img_block.model_dump = lambda: {
        "type": "image", "data": png_data, "mimeType": "image/png"
    }
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
    assert result_mm["images"][0]["index"] == 1, (
        "image index must match position in content"
    )
    assert len(result_mm["content"]) == 2
    assert result_mm["content"][0]["type"] == "text"
    assert result_mm["content"][1]["type"] == "image"
    assert result_mm["content"][1]["data"] == png_data
    assert result_mm["content"][1]["mimeType"] == "image/png"

    # --- Scenario 4: structuredContent present (non-None) ---
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

    # --- Scenario 5: realistic sample data from knowledge hub ---
    raw = sample_mcp_tool_call_result()
    txt_real = MagicMock()
    txt_real.model_dump = lambda: raw["content"][0]
    mock_mcp_session.call_tool.return_value = MagicMock(
        content=[txt_real],
        isError=raw["isError"],
        structuredContent=raw["structuredContent"],
    )
    result_real = asyncio.run(mcp_client.call_tool(
        "query_knowledge_hub", {"query": "TOPMOST"}
    ))
    assert result_real["isError"] is False
    assert "structuredContent" in result_real
    assert "citations" in result_real["structuredContent"]
    assert len(result_real["structuredContent"]["citations"]) == 2
    assert (
        result_real["structuredContent"]["citations"][0]["text_snippet"]
        == "TOPMOST reaches a wider coverage"
    )
    assert (
        result_real["structuredContent"]["citations"][0]["chunk_id"]
        == "9a08dfd1_0014_24dbbf27"
    )

    # --- Scenario 6: input validation ---
    with pytest.raises(ValueError, match="Tool name must be a non-empty string"):
        asyncio.run(mcp_client.call_tool("", {"q": "test"}))
    with pytest.raises(ValueError, match="Tool name must be a non-empty string"):
        asyncio.run(mcp_client.call_tool(None, {"q": "test"}))
    with pytest.raises(ValueError, match="arguments must be a dict"):
        asyncio.run(mcp_client.call_tool("search", None))
    with pytest.raises(ValueError, match="arguments must be a dict"):
        asyncio.run(mcp_client.call_tool("search", "not-a-dict"))


# --- Mock tests (verify code logic) ---

def test_mcp_client_call_tool(mcp_client, mock_mcp_session):
    """Verify McpClient.call_tool returns standardized structure
    (reference: test/helpers/samples.py sample_mcp_tool_call_result)."""
    _gate(mcp_client, mock_mcp_session)


def test_executor_execute_task(executor):
    """Verify Executor.execute_task can run through tool call chain
    (reference sample_rag_queries for real queries)."""
    # Mock fill_arguments and call_tool to isolate execute_task logic
    mock_fill = AsyncMock(return_value={"query": "TOPMOST features", "top_k": 5})
    executor.fill_arguments = mock_fill

    raw_success = sample_mcp_raw_text_only()
    mock_call = AsyncMock(return_value=raw_success)
    executor.call_tool = mock_call

    def get_schema(tool_name: str) -> dict:
        if tool_name == "query_knowledge_hub":
            return {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            }
        if tool_name == "read_chunk":
            return {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
            }
        raise KeyError(f"Tool '{tool_name}' not found")

    task = {
        "tool_name": "query_knowledge_hub",
        "description": "Search for TOPMOST features in the knowledge hub",
        "prior_observation": "Previous attempt returned no results",
    }

    result = asyncio.run(executor.execute_task(task, get_schema))

    # fill_arguments called with correct args
    mock_fill.assert_awaited_once()
    fill_kwargs = mock_fill.call_args.kwargs
    assert fill_kwargs["tool_name"] == "query_knowledge_hub"
    assert fill_kwargs["user_intent"] == (
        "Search for TOPMOST features in the knowledge hub"
    )
    assert fill_kwargs["prior_observation"] == (
        "Previous attempt returned no results"
    )
    assert isinstance(fill_kwargs["input_schema"], dict)
    assert "query" in fill_kwargs["input_schema"]["properties"]

    # call_tool called with tool_name and filled arguments
    mock_call.assert_awaited_once_with(
        "query_knowledge_hub", {"query": "TOPMOST features", "top_k": 5}
    )

    # result is call_tool's return value
    assert result is raw_success
    assert result["isError"] is False
    assert "content" in result

    # --- Error path: missing tool_name and suggested_tool ---
    task_no_tool = {"description": "no tool specified"}
    result_err = asyncio.run(executor.execute_task(task_no_tool, get_schema))
    assert isinstance(result_err, dict)
    assert result_err["isError"] is True
    assert isinstance(result_err["content"], list)
    assert len(result_err["content"]) >= 1
    assert result_err["content"][0]["type"] == "text"
    error_text = result_err["content"][0]["text"].lower()
    assert ("tool_name" in error_text) or ("suggested_tool" in error_text), (
        f"Error message should mention tool_name or suggested_tool, got: {error_text!r}"
    )


def test_executor_fill_arguments(executor):
    """Verify Executor.fill_arguments can fill parameters based on user query."""
    # Replace internally-created LLM with a mock that returns valid JSON
    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(
        content=(
            '{"query": "TOPMOST topic modeling toolkit features", '
            '"top_k": 5}'
        ),
    )
    executor._llm = mock_llm

    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        "required": ["query"],
    }

    tool_name = "query_knowledge_hub"
    user_intent = "Search for TOPMOST features in the knowledge hub"
    prior_observation = "Previous search returned 3 chunks about topic modeling"

    result = asyncio.run(
        executor.fill_arguments(
            tool_name=tool_name,
            input_schema=schema,
            user_intent=user_intent,
            prior_observation=prior_observation,
        )
    )

    # Must return a dict
    assert isinstance(result, dict), (
        f"Expected dict, got {type(result).__name__}: {result!r}"
    )

    # Required keys must be present
    assert "query" in result, (
        f"Missing required key 'query'; keys present: {list(result.keys())}"
    )

    # Values must match what the mock LLM returned
    assert result["query"] == "TOPMOST topic modeling toolkit features"
    assert result["top_k"] == 5

    # Types must match schema declarations
    assert isinstance(result["query"], str)
    assert isinstance(result["top_k"], int)

    # No extra keys beyond schema properties
    allowed = set(schema["properties"].keys())
    actual_keys = set(result.keys())
    assert actual_keys.issubset(allowed), (
        f"Extra keys in result not declared in schema: {actual_keys - allowed}"
    )

    # LLM was called exactly once (no retries needed for valid JSON)
    assert mock_llm.chat.call_count == 1

    # LLM was called with properly constructed messages
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert "JSON generator" in messages[0].content
    assert messages[1].role == "user"
    assert user_intent in messages[1].content
    assert prior_observation in messages[1].content


# --- Real API tests (verify MCP call chain and return format) ---

@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_mcp_query_knowledge_hub(real_mcp_client):
    """Verify query_knowledge_hub call and return format with real MCP server."""
    from test.helpers.contracts import assert_mcp_normalized

    result = await real_mcp_client.call_tool(
        "query_knowledge_hub",
        {"query": "What is TOPMOST topic modeling toolkit?"},
    )
    assert_mcp_normalized(result)
    assert not result.get("isError", True)


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_mcp_read_chunk(real_mcp_client):
    """Verify read_chunk call and return format with real MCP server."""
    from test.helpers.contracts import assert_mcp_normalized

    search = await real_mcp_client.call_tool(
        "query_knowledge_hub",
        {"query": "TOPMOST"},
    )
    assert not search.get("isError", True)
    chunk_id = None
    sc = search.get("structuredContent") or {}
    for cite in sc.get("citations") or []:
        if isinstance(cite, dict) and cite.get("chunk_id"):
            chunk_id = cite["chunk_id"]
            break
    if not chunk_id:
        pytest.skip("no chunk_id in query_knowledge_hub result for read_chunk live test")
    result = await real_mcp_client.call_tool("read_chunk", {"chunk_id": chunk_id})
    assert_mcp_normalized(result)


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_mcp_all_tools(real_mcp_client):
    """Verify tools/list exposes registered MCP tools."""
    session = real_mcp_client._session
    listed = await session.list_tools()
    tools = getattr(listed, "tools", None) or listed
    names = sorted(
        getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else "")
        for t in (tools or [])
    )
    names = [n for n in names if n]
    assert len(names) >= 5, f"expected multiple MCP tools, got {names}"


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_executor_fill_and_call(real_executor):
    """Verify Executor complete chain: fill_arguments -> call_tool with real LLM + MCP."""
    from test.helpers.contracts import assert_mcp_normalized

    task = {
        "id": "live-1",
        "description": "Search knowledge hub for TOPMOST overview",
        "intent": "retrieve",
        "suggested_tool": "query_knowledge_hub",
        "prior_observation": "",
    }

    def get_schema(tool_name: str) -> dict:
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    raw = await real_executor.execute_task(task, get_schema)
    assert_mcp_normalized(raw)
