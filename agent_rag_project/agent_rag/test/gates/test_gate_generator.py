"""§6 — Generator 功能门禁验收。"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from test.helpers.contracts import assert_next_action_result

pytestmark = [pytest.mark.gate]


def _mock_llm(content: str):
    mock = MagicMock()
    mock.chat.return_value = MagicMock(content=content)
    return mock


def test_generator_init(generator):
    assert generator is not None
    assert hasattr(generator, "_inner_trace")
    assert hasattr(generator, "reset_subtask_state")


@pytest.mark.asyncio
async def test_choose_next_action_returns_valid(generator):
    generator._llm = _mock_llm(
        json.dumps({"action": "stop", "tool_name": "", "reason": "enough evidence"})
    )
    result = await generator.choose_next_action(
        "What is TOPMOST?",
        {"description": "Find TOPMOST info", "intent": "retrieve"},
        [],
        tool_names=["query_knowledge_hub"],
    )
    assert_next_action_result(result)


@pytest.mark.asyncio
async def test_draft_partial_answer_returns_str(generator):
    generator._llm = _mock_llm("TOPMOST is a topic modeling toolkit.")
    result = await generator.draft_partial_answer(
        "What is TOPMOST?",
        {"description": "Find features", "intent": "retrieve"},
        "query_knowledge_hub: 3 document hits",
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_summarize_mcp_result(generator, mock_mcp_raw_text, mock_mcp_raw_multimodal, mock_mcp_raw_error):
    assert "hello" in generator.summarize_mcp_result(mock_mcp_raw_text)
    assert "[error]" in generator.summarize_mcp_result(mock_mcp_raw_error)
    s = generator.summarize_mcp_result(mock_mcp_raw_multimodal)
    assert "图" in s or "image" in s.lower()


def test_format_trace(generator):
    empty = generator._format_trace([])
    assert empty
    formatted = generator._format_trace([{"tool_name": "t", "summary": "ok"}])
    assert "t" in formatted and "ok" in formatted


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_choose_next_action_prompt(real_llm, config):
    from agent_rag.agents.generator import Generator
    from test.helpers.contracts import assert_next_action_result

    rag_cfg = dict(config.get("rag_agent", {}) or {})
    rag_cfg["llm"] = config.get("llm", {})
    gen = Generator(config=rag_cfg)
    gen._llm = real_llm
    gen._config["cold_start_use_suggested_tool"] = False
    result = await gen.choose_next_action(
        "What is TOPMOST?",
        {"description": "Find TOPMOST features", "intent": "retrieve"},
        [{"tool_name": "query_knowledge_hub", "ok": True, "summary": "3 hits"}],
        tool_names=["query_knowledge_hub", "search_by_metadata"],
    )
    assert_next_action_result(result)


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_real_draft_partial_answer_prompt(real_llm, config):
    from agent_rag.agents.generator import Generator

    rag_cfg = dict(config.get("rag_agent", {}) or {})
    rag_cfg["llm"] = config.get("llm", {})
    gen = Generator(config=rag_cfg)
    gen._llm = real_llm
    result = await gen.draft_partial_answer(
        "What is TOPMOST?",
        {"description": "Summarize TOPMOST purpose", "intent": "retrieve"},
        "query_knowledge_hub: TOPMOST is a topic modeling toolkit for fair comparison.",
    )
    assert isinstance(result, str)
    assert len(result.strip()) > 20
