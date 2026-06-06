"""Unit tests for Executor.call_tool. See docs/test_outline.md phase 4.3."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from test.helpers.samples import sample_mcp_raw_text_only

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# retry / backoff / normalisation
# ---------------------------------------------------------------------------

def test_retry(executor):
    """call_tool retries on transient failures with exponential backoff,
    normalises result dicts, and returns an isError dict when retries are exhausted.
    """

    executor._config["max_retries"] = 3
    executor._config["backoff_base_sec"] = 1.0

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # --- Scenario 1: transient failures then success --------------------
        call_count = 0

        async def flaky_then_ok(name, arguments):
            nonlocal call_count
            call_count += 1
            if call_count < 4:  # fail first 3 of 4 attempts
                raise RuntimeError("transient MCP error")
            return sample_mcp_raw_text_only()

        executor._mcp.call_tool = AsyncMock(side_effect=flaky_then_ok)

        result = asyncio.run(executor.call_tool("search", {"q": "test"}))

        assert call_count == 4, (
            f"expected 4 attempts (3 failures + 1 success), got {call_count}"
        )
        assert isinstance(result, dict)
        assert "content" in result
        assert "isError" in result
        assert result["isError"] is False
        # Verify exponential backoff waits: 1.0, 2.0, 4.0
        assert mock_sleep.call_count == 3
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)

        # --- Scenario 2: all attempts fail -> isError dict (no exception) ---
        mock_sleep.reset_mock()
        call_count = 0

        async def always_fail(name, arguments):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("persistent MCP error")

        executor._mcp.call_tool = AsyncMock(side_effect=always_fail)

        result = asyncio.run(executor.call_tool("search", {"q": "test"}))

        assert call_count == 4, (
            f"expected 4 attempts before exhaustion, got {call_count}"
        )
        assert isinstance(result, dict)
        assert result["isError"] is True
        assert isinstance(result["content"], list)
        assert len(result["content"]) >= 1
        assert result["content"][0]["type"] == "text"
        assert "failed after 4 attempts" in result["content"][0]["text"]
        assert mock_sleep.call_count == 3

        # --- Scenario 3: non-dict result normalised to error shape ---------
        mock_sleep.reset_mock()

        async def return_non_dict(name, arguments):
            return "not a dict"

        executor._mcp.call_tool = AsyncMock(side_effect=return_non_dict)

        result = asyncio.run(executor.call_tool("search", {"q": "test"}))
        assert isinstance(result, dict)
        assert result["content"] == []
        assert result["isError"] is True

        # --- Scenario 4: result missing isError / content gets defaults ----
        async def return_missing_keys(name, arguments):
            return {}

        executor._mcp.call_tool = AsyncMock(side_effect=return_missing_keys)

        result = asyncio.run(executor.call_tool("search", {"q": "test"}))
        assert result["isError"] is False
        assert result["content"] == []


# ---------------------------------------------------------------------------
# input validation
# ---------------------------------------------------------------------------

def test_call_tool_invalid_name(executor):
    """call_tool raises ValueError when tool name is not a non-empty string."""
    valid_args = {"q": "test"}

    with pytest.raises(ValueError, match="Tool name must be a non-empty string"):
        asyncio.run(executor.call_tool("", valid_args))

    with pytest.raises(ValueError, match="Tool name must be a non-empty string"):
        asyncio.run(executor.call_tool(None, valid_args))

    with pytest.raises(ValueError, match="Tool name must be a non-empty string"):
        asyncio.run(executor.call_tool(123, valid_args))


def test_call_tool_invalid_arguments(executor):
    """call_tool raises ValueError when arguments is not a dict."""
    valid_name = "search"

    with pytest.raises(ValueError, match="arguments must be a dict"):
        asyncio.run(executor.call_tool(valid_name, None))

    with pytest.raises(ValueError, match="arguments must be a dict"):
        asyncio.run(executor.call_tool(valid_name, "not-a-dict"))

    with pytest.raises(ValueError, match="arguments must be a dict"):
        asyncio.run(executor.call_tool(valid_name, [1, 2, 3]))


# ---------------------------------------------------------------------------
# max_retries=0 edge cases
# ---------------------------------------------------------------------------

def test_call_tool_max_retries_zero_success(executor):
    """When max_retries=0 and the call succeeds on the first attempt, result is returned."""
    executor._config["max_retries"] = 0
    executor._config["backoff_base_sec"] = 1.0

    expected = {"content": [{"text": "ok"}], "isError": False}
    executor._mcp.call_tool = AsyncMock(return_value=expected)

    result = asyncio.run(executor.call_tool("fetch", {"id": 1}))
    assert result == expected
    executor._mcp.call_tool.assert_awaited_once_with("fetch", {"id": 1})


def test_call_tool_max_retries_zero_failure(executor):
    """When max_retries=0 and the call fails, an isError dict is returned
    (not an exception), no sleep is performed, and exactly 1 attempt is made."""
    executor._config["max_retries"] = 0
    executor._config["backoff_base_sec"] = 1.0

    async def fail_once(name, arguments):
        raise RuntimeError("boom")

    executor._mcp.call_tool = AsyncMock(side_effect=fail_once)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = asyncio.run(executor.call_tool("fetch", {}))

        # Must return an isError dict, not raise
        assert isinstance(result, dict)
        assert result["isError"] is True
        assert isinstance(result["content"], list)
        assert len(result["content"]) >= 1
        assert result["content"][0]["type"] == "text"
        assert "failed after 1 attempts" in result["content"][0]["text"]

        # Only one call was attempted
        assert executor._mcp.call_tool.await_count == 1
        # No backoff sleep should be scheduled when max_retries=0
        mock_sleep.assert_not_awaited()


# ---------------------------------------------------------------------------
# result normalisation
# ---------------------------------------------------------------------------

def test_call_tool_result_none_normalized(executor):
    """None result is normalised to an error-shape dict."""
    executor._config["max_retries"] = 1
    executor._mcp.call_tool = AsyncMock(return_value=None)

    result = asyncio.run(executor.call_tool("search", {"q": "x"}))
    assert result == {"content": [], "isError": True}


def test_call_tool_result_string_normalized(executor):
    """A non-dict string result is normalised to error shape."""
    executor._config["max_retries"] = 1
    executor._mcp.call_tool = AsyncMock(return_value="raw string")

    result = asyncio.run(executor.call_tool("search", {"q": "x"}))
    assert result == {"content": [], "isError": True}


def test_call_tool_preserves_extra_result_keys(executor):
    """Successful call returns a dict preserving extra keys while adding defaults."""
    executor._config["max_retries"] = 1
    raw = {"content": [{"text": "found"}], "extra": 42}
    executor._mcp.call_tool = AsyncMock(return_value=raw)

    result = asyncio.run(executor.call_tool("lookup", {"key": "val"}))
    assert result["isError"] is False
    assert result["content"] == [{"text": "found"}]
    assert result["extra"] == 42
    assert "content" in result
    assert "isError" in result


# ---------------------------------------------------------------------------
# backoff
# ---------------------------------------------------------------------------

def test_call_tool_retry_backoff_with_different_base(executor):
    """Backoff sleep uses the configured backoff_base_sec."""
    executor._config["max_retries"] = 2          # 3 attempts total
    executor._config["backoff_base_sec"] = 0.5

    call_count = 0

    async def fail_two_then_ok(name, arguments):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("fail")
        return sample_mcp_raw_text_only()

    executor._mcp.call_tool = AsyncMock(side_effect=fail_two_then_ok)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = asyncio.run(executor.call_tool("s", {"x": 1}))
        assert result["isError"] is False
        assert call_count == 3
        assert mock_sleep.await_count == 2
        # First retry after 0.5 * 2^0 = 0.5, second after 0.5 * 2^1 = 1.0
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)
