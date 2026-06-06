"""Unit tests for Executor.fill_arguments. See docs/test_outline.md phase 3.5."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]


def test_valid_json(executor):
    """fill_arguments returns a valid dict when the LLM produces well-formed JSON
    that satisfies the provided input_schema, with required keys present, correct
    types, and no extra keys beyond the schema properties."""

    # Replace the internally-created LLM with a mock that returns valid JSON
    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(
        content='{"query": "TOPMOST topic modeling toolkit features", "top_k": 5}',
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
    assert result["query"] == "TOPMOST topic modeling toolkit features", (
        f"Unexpected query value: {result['query']!r}"
    )
    assert result["top_k"] == 5, (
        f"Unexpected top_k value: {result['top_k']!r}"
    )

    # Types must match schema declarations
    assert isinstance(result["query"], str), (
        f"'query' must be str, got {type(result['query']).__name__}"
    )
    assert isinstance(result["top_k"], int), (
        f"'top_k' must be int, got {type(result['top_k']).__name__}"
    )

    # No extra keys beyond what the schema declares (spec rejects undeclared keys
    # when properties is non-empty)
    allowed = set(schema["properties"].keys())
    actual = set(result.keys())
    assert actual.issubset(allowed), (
        f"Extra keys in result not declared in schema: {actual - allowed}"
    )

    # The mock LLM was called exactly once (no retries needed for valid JSON)
    assert mock_llm.chat.call_count == 1, (
        f"Expected 1 LLM call, got {mock_llm.chat.call_count}"
    )

    # Verify the LLM was called with properly constructed messages
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    assert len(messages) == 2, (
        f"Expected 2 messages (system + user), got {len(messages)}"
    )
    assert messages[0].role == "system", (
        f"First message role should be 'system', got {messages[0].role!r}"
    )
    assert "JSON generator" in messages[0].content, (
        "System prompt missing expected instruction text"
    )
    assert messages[1].role == "user", (
        f"Second message role should be 'user', got {messages[1].role!r}"
    )
    # User prompt must contain the schema, user intent, and prior observation
    assert user_intent in messages[1].content, (
        f"User intent not found in user prompt"
    )
    assert prior_observation in messages[1].content, (
        f"Prior observation not found in user prompt"
    )
    assert "top_k" in messages[1].content, (
        "Schema property 'top_k' not found in user prompt (schema not injected)"
    )
