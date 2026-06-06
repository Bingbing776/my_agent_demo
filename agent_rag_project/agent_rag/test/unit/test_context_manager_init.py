"""Unit tests for ContextManager.__init__ per tech_doc section 2."""
import pytest

pytestmark = [pytest.mark.unit]

def test_empty_window(context_manager):
    """context_window must be initialized as an empty list after init."""
    assert context_manager.context_window == []
    assert isinstance(context_manager.context_window, list)
    # config is stored and scalar defaults are applied per tech_doc section 2
    assert hasattr(context_manager, 'config')
    assert isinstance(context_manager.config, dict)
    assert context_manager.max_context_count == 10
    assert context_manager.compress_top_k == 5
    assert context_manager.compress_token_limit == 2000
    assert context_manager.max_len is None
    # LLM and DenseEncoder are eagerly initialized during __init__
    assert context_manager._llm is not None
    assert context_manager._encoder is not None
