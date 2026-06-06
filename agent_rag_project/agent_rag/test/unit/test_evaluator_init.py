"""Unit tests for Evaluator.__init__ per tech_doc sec5."""
import pytest

pytestmark = [pytest.mark.unit]


def test_constructs(evaluator):
    """Evaluator.__init__ sets _config, _llm, and does not hold MCP/Executor."""
    assert evaluator is not None

    # _config must be stored as dict (default {} when None/omitted)
    assert hasattr(evaluator, '_config')
    assert isinstance(evaluator._config, dict)

    # _llm must be created internally via LLMFactory.create, not injected
    assert hasattr(evaluator, '_llm')
    assert evaluator._llm is not None

    # Must NOT hold Executor or McpClient references (sec5 constraint)
    assert not hasattr(evaluator, '_executor')
    assert not hasattr(evaluator, '_mcp')
    assert not hasattr(evaluator, '_mcp_client')

    # Config-derived attributes set in __init__
    assert hasattr(evaluator, '_eval_max_chars')
    assert isinstance(evaluator._eval_max_chars, int)
    assert evaluator._eval_max_chars > 0

    assert hasattr(evaluator, '_strict_json')
    assert isinstance(evaluator._strict_json, bool)

    assert hasattr(evaluator, '_eval_system_prompt')
    assert isinstance(evaluator._eval_system_prompt, str)
    assert len(evaluator._eval_system_prompt) > 0

    # _llm must have a callable chat method
    assert hasattr(evaluator._llm, 'chat')
    assert callable(evaluator._llm.chat)
