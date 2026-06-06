"""Unit tests for Executor.__init__ (stage 3.3 / task 3.3).

Verifies that the constructor correctly stores the McpClient as _mcp,
the config dict as _config (defaulting to {}), and creates _llm via
_create_llm which uses LLMFactory or falls back to a stub.
"""
import pytest
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]

from test.helpers.imports import import_class


class TestExecutorInit:
    """Group: Executor.__init__ storage, defaults, and LLM creation."""

    # -- _mcp ---------------------------------------------------------------

    def test_stores_mcp_client_as_mcp(self, executor, mcp_client):
        """_mcp must be the exact McpClient instance passed in."""
        assert hasattr(executor, "_mcp")
        assert executor._mcp is mcp_client

    def test_fixture_mcp_not_none(self, executor):
        """Fixture-provided Executor must have a non-None _mcp."""
        assert executor._mcp is not None

    # -- _config ------------------------------------------------------------

    def test_stores_config_dict(self, executor, config):
        """_config must hold the config dict supplied at construction."""
        expected = config.get("rag_agent", {})
        assert hasattr(executor, "_config")
        assert executor._config == expected
        assert isinstance(executor._config, dict)

    def test_config_none_yields_empty_dict(self):
        """Explicit config=None must still produce {} as _config."""
        cls = import_class("Executor")
        mock_mcp = MagicMock()
        e = cls(mcp_client=mock_mcp, config=None)
        assert e._config == {}

    def test_config_omitted_yields_empty_dict(self):
        """When config is not given, _config must default to {}."""
        cls = import_class("Executor")
        mock_mcp = MagicMock()
        e = cls(mcp_client=mock_mcp)
        assert e._config == {}

    def test_both_mcp_and_config_stored_simultaneously(self, executor, mcp_client, config):
        """A single instance must correctly store both _mcp and _config."""
        assert executor._mcp is mcp_client
        expected_cfg = config.get("rag_agent", {})
        assert executor._config == expected_cfg

    # -- _llm ---------------------------------------------------------------

    def test_llm_created_and_non_null(self, executor):
        """_llm is created during __init__ and is not None."""
        assert hasattr(executor, "_llm")
        assert executor._llm is not None

    def test_llm_has_chat_method(self, executor):
        """The created _llm must expose a callable chat method."""
        assert hasattr(executor._llm, "chat")
        assert callable(executor._llm.chat)

    def test_llm_creation_method_exists(self, executor):
        """_create_llm method exists and is callable."""
        assert hasattr(executor, "_create_llm")
        assert callable(executor._create_llm)

    def test_llm_creation_uses_internal_factory_not_injected(self, executor):
        """_llm is created by internal _create_llm, not injected from outside.

        The spec forbids passing llm from outside; __init__ must call
        _create_llm internally.  We verify this by checking that _llm
        exists and is usable without any external llm injection.
        """
        assert executor._llm is not None
        # The stub fallback in _create_llm returns an object whose chat
        # returns ChatResponse with .content attribute.
        assert hasattr(executor._llm, "chat")

    # -- all three attributes together -------------------------------------

    def test_all_three_attributes_present_after_init(self, executor, mcp_client):
        """After __init__, _mcp, _config, and _llm are all set."""
        assert hasattr(executor, "_mcp")
        assert hasattr(executor, "_config")
        assert hasattr(executor, "_llm")
        assert executor._mcp is mcp_client
        assert isinstance(executor._config, dict)
        assert executor._llm is not None
