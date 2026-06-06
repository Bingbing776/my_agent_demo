"""Unit tests for Executor.execute_task. See docs/test_outline.md phase 3.6."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.helpers.samples import sample_mcp_raw_text_only

pytestmark = [pytest.mark.unit]


def test_fill_then_call(executor):
    """execute_task integrates fill_arguments and call_tool:
    extracts tool_name (or suggested_tool) from task, fetches the input
    schema via get_input_schema, calls fill_arguments with user_intent and
    prior_observation, then calls call_tool with the filled arguments.
    Error paths (missing tool_name, schema KeyError, fill_arguments exception)
    all return a normalized isError=True dict without raising."""

    # ---- mocks -----------------------------------------------------------
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

    # ---- Scenario 1: happy path with tool_name ---------------------------
    task1 = {
        "tool_name": "query_knowledge_hub",
        "description": "Search for TOPMOST features in the knowledge hub",
        "prior_observation": "Previous attempt returned no results",
    }

    result1 = asyncio.run(executor.execute_task(task1, get_schema))

    # fill_arguments called with correct args
    mock_fill.assert_awaited_once()
    fill_kwargs = mock_fill.call_args.kwargs
    assert fill_kwargs["tool_name"] == "query_knowledge_hub"
    assert fill_kwargs["user_intent"] == "Search for TOPMOST features in the knowledge hub"
    assert fill_kwargs["prior_observation"] == "Previous attempt returned no results"
    assert isinstance(fill_kwargs["input_schema"], dict)
    assert "query" in fill_kwargs["input_schema"]["properties"]

    # call_tool called with tool_name and filled arguments
    mock_call.assert_awaited_once_with("query_knowledge_hub", {"query": "TOPMOST features", "top_k": 5})

    # result is call_tool's return value
    assert result1 is raw_success
    assert result1["isError"] is False
    assert "content" in result1

    # ---- Scenario 2: suggested_tool fallback -----------------------------
    mock_fill.reset_mock()
    mock_call.reset_mock()

    task2 = {
        "suggested_tool": "read_chunk",
        "description": "Read chunk c1",
        "prior_observation": "",
    }

    result2 = asyncio.run(executor.execute_task(task2, get_schema))

    mock_fill.assert_awaited_once()
    assert mock_fill.call_args.kwargs["tool_name"] == "read_chunk"
    mock_call.assert_awaited_once()
    assert mock_call.call_args.args[0] == "read_chunk"
    assert result2 is raw_success

    # ---- Scenario 3: tool_name takes precedence over suggested_tool ------
    mock_fill.reset_mock()
    mock_call.reset_mock()

    task3 = {
        "tool_name": "query_knowledge_hub",
        "suggested_tool": "read_chunk",
        "description": "Query the hub",
    }

    asyncio.run(executor.execute_task(task3, get_schema))
    assert mock_fill.call_args.kwargs["tool_name"] == "query_knowledge_hub"

    # ---- Scenario 4: missing tool_name and suggested_tool -> isError -----
    task4 = {"description": "no tool specified at all"}
    result4 = asyncio.run(executor.execute_task(task4, get_schema))

    assert isinstance(result4, dict)
    assert result4["isError"] is True
    assert isinstance(result4["content"], list)
    assert len(result4["content"]) >= 1
    assert result4["content"][0]["type"] == "text"
    error_text4 = result4["content"][0]["text"].lower()
    assert ("tool_name" in error_text4) or ("suggested_tool" in error_text4), (
        f"Error message should mention tool_name or suggested_tool, got: {error_text4!r}"
    )

    # ---- Scenario 5: empty tool_name after strip -> isError ---------------
    task5 = {"tool_name": "   ", "description": "whitespace only tool name"}
    result5 = asyncio.run(executor.execute_task(task5, get_schema))

    assert result5["isError"] is True
    assert len(result5["content"]) >= 1
    assert result5["content"][0]["type"] == "text"

    # ---- Scenario 6: get_input_schema raises KeyError -> isError ---------
    task6 = {"tool_name": "nonexistent_tool", "description": "bad tool"}
    result6 = asyncio.run(executor.execute_task(task6, get_schema))

    assert result6["isError"] is True
    assert isinstance(result6["content"], list)
    assert len(result6["content"]) >= 1
    assert result6["content"][0]["type"] == "text"
    assert "nonexistent_tool" in result6["content"][0]["text"]
    assert "not found" in result6["content"][0]["text"].lower()

    # fill_arguments and call_tool must NOT have been called after the
    # schema error (reset mocks first to avoid counting Scenario 5 calls)
    mock_fill.reset_mock()
    mock_call.reset_mock()

    task6b = {"tool_name": "also_missing", "description": "another bad tool"}
    asyncio.run(executor.execute_task(task6b, get_schema))
    mock_fill.assert_not_awaited()
    mock_call.assert_not_awaited()

    # ---- Scenario 7: fill_arguments raises exception -> isError -----------
    mock_fill.side_effect = Exception("LLM failed to produce valid JSON after retries")
    mock_fill.reset_mock()
    mock_call.reset_mock()

    task7 = {"tool_name": "query_knowledge_hub", "description": "will fail fill"}
    result7 = asyncio.run(executor.execute_task(task7, get_schema))

    assert result7["isError"] is True
    assert isinstance(result7["content"], list)
    assert len(result7["content"]) >= 1
    assert result7["content"][0]["type"] == "text"
    assert "Failed to generate valid arguments" in result7["content"][0]["text"]
    assert "query_knowledge_hub" in result7["content"][0]["text"]

    # call_tool must NOT be called when fill_arguments fails
    mock_call.assert_not_awaited()

    # ---- Scenario 8: call_tool error propagated correctly -----------------
    mock_fill.side_effect = None
    mock_fill.return_value = {"chunk_id": "abc123"}
    mock_fill.reset_mock()
    mock_call.reset_mock()

    call_error = {
        "content": [{"type": "text", "text": "MCP server timeout"}],
        "isError": True,
    }
    mock_call.return_value = call_error

    task8 = {"tool_name": "read_chunk", "description": "read abc123"}
    result8 = asyncio.run(executor.execute_task(task8, get_schema))

    # The error from call_tool is passed through
    assert result8 is call_error
    assert result8["isError"] is True

    # ---- Scenario 9: prior_observation defaults to empty string -----------
    mock_fill.reset_mock()
    mock_call.reset_mock()
    mock_call.return_value = raw_success

    task9 = {
        "tool_name": "query_knowledge_hub",
        "description": "Search without prior observation",
    }

    asyncio.run(executor.execute_task(task9, get_schema))
    fill_kwargs9 = mock_fill.call_args.kwargs
    # prior_observation should be empty string when key is absent
    assert fill_kwargs9["prior_observation"] == ""

    # ---- Scenario 10: result dict always has content and isError keys -----
    # This is verified across all scenarios above; add an explicit check
    # on the happy-path result shape
    assert "content" in result1
    assert "isError" in result1
    assert isinstance(result1["content"], list)
    assert isinstance(result1["isError"], bool)
