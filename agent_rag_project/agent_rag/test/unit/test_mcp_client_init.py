"""Unit tests for McpClient.__init__ (stage 3.1 / task 3.1).

Verifies that the constructor correctly stores the underlying MCP session\nas `_session` and the config dict as `_config`, with default `{}`\nbehaviour when no config is supplied.
"""
import pytest
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]

from agent_rag.mcp.mcp_client import McpClient


class TestMcpClientInit:
    """Group: McpClient.__init__ storage and defaults."""

    def test_stores_underlying_session(self):
        """_session must be the exact object passed as underlying_session."""
        mock_session = MagicMock(name="underlying_session")
        client = McpClient(underlying_session=mock_session)
        assert client._session is mock_session

    def test_stores_config_dict(self):
        """_config must hold the caller-supplied config dict."""
        mock_session = MagicMock()
        cfg = {"call_tool_timeout_sec": 30, "max_retries": 3}
        client = McpClient(underlying_session=mock_session, config=cfg)
        # For a truthy dict the 'or' operator returns the original object,
        # so identity is preserved.
        assert client._config is cfg
        assert client._config == {"call_tool_timeout_sec": 30, "max_retries": 3}

    def test_config_defaults_to_empty_dict_when_omitted(self):
        """When config is not given, _config must be an empty dict."""
        mock_session = MagicMock()
        client = McpClient(underlying_session=mock_session)
        assert client._config == {}
        assert isinstance(client._config, dict)

    def test_config_none_yields_empty_dict(self):
        """Explicit config=None must still produce {} as _config."""
        mock_session = MagicMock()
        client = McpClient(underlying_session=mock_session, config=None)
        assert client._config == {}

    def test_both_session_and_config_stored_simultaneously(self):
        """A single instance must correctly store both _session and _config."""
        mock_session = MagicMock()
        cfg = {"timeout": 10}
        client = McpClient(underlying_session=mock_session, config=cfg)
        assert client._session is mock_session
        assert client._config is cfg
        assert client._config == {"timeout": 10}

    def test_fixture_stores_session(self, mcp_client):
        """Fixture-provided McpClient must expose a non-None _session."""
        assert mcp_client is not None
        assert hasattr(mcp_client, "_session")
        assert mcp_client._session is not None

    def test_fixture_stores_config_as_dict(self, mcp_client):
        """Fixture-provided McpClient must have _config set to a dict."""
        assert hasattr(mcp_client, "_config")
        assert isinstance(mcp_client._config, dict)
