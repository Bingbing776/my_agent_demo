"""共享 fixture。见 docs/test_outline.md 阶段 0。

测试策略：
- Mock fixture（mock_llm、mock_mcp_session）：用于快速 unit/gates 测试，验证代码逻辑
- Real fixture（real_llm、real_mcp_session）：用于 @pytest.mark.llm_live 测试，验证：
  1. Prompt 质量：真实 LLM 能否按预期返回正确格式
  2. 真实返回格式：与 mock 假设的格式是否一致
  3. MCP 调用链路：McpClient/Executor → session → server 是否正确

使用建议：
- 每个有 LLM/MCP 调用的函数：多个 mock 测试 + 1 个 @pytest.mark.llm_live 测试
- Mock 的返回格式应基于真实 API 观察（见 test/helpers/samples.py），不要凭空假设
- 改了 prompt 或调用逻辑后必须跑 pytest -m llm_live 验证
- llm_live 自动加载 config/settings.llm_live.yaml（与 settings.yaml deep-merge）；MCP 子进程经 MODULAR_RAG_SETTINGS_PATH 加载 mcp_rag/config/settings.llm_live.yaml
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

try:
    import pytest_asyncio
except ImportError:
    pytest_asyncio = None  # type: ignore[assignment]


def _async_fixture(*args, **kwargs):
    if pytest_asyncio is not None:
        return pytest_asyncio.fixture(*args, **kwargs)
    return pytest.fixture(*args, **kwargs)

# 仓库根、agent_rag 包、MODULAR 父仓（tech_doc：from src.libs / src.ingestion）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG_ROOT = Path(__file__).resolve().parents[1]
_MODULAR_ROOT = _REPO_ROOT / "mcp_rag"
for p in (_REPO_ROOT, _PKG_ROOT, _MODULAR_ROOT):
    s = str(p)
    if p.is_dir() and s not in sys.path:
        sys.path.insert(0, s)

from test.helpers.imports import import_class, is_llm_live_requested, load_config, load_config_llm_live
from test.helpers.samples import (
    sample_mcp_raw_error,
    sample_mcp_raw_multimodal,
    sample_mcp_raw_text_only,
)


def pytest_configure(config: pytest.Config) -> None:
    markexpr = getattr(config.option, "markexpr", "") or ""
    if markexpr and "llm_live" in markexpr and "not llm_live" not in markexpr:
        os.environ.setdefault("AGENT_RAG_LLM_LIVE", "1")


def _active_config() -> dict[str, Any]:
    if is_llm_live_requested():
        return load_config_llm_live()
    return load_config()


@pytest.fixture
def config(request: pytest.FixtureRequest) -> dict[str, Any]:
    if request.node.get_closest_marker("llm_live") is not None:
        return load_config_llm_live()
    return load_config()


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = '{"action": "stop"}'
    return llm


@pytest.fixture
def mock_mcp_session() -> MagicMock:
    session = MagicMock()
    session.call_tool.return_value = MagicMock(
        content=[MagicMock(type="text", text="ok", model_dump=lambda: {"type": "text", "text": "ok"})],
        isError=False,
        structuredContent=None,
    )
    return session


@pytest.fixture
def mock_mcp_raw_text() -> dict[str, Any]:
    return sample_mcp_raw_text_only()


@pytest.fixture
def mock_mcp_raw_multimodal() -> dict[str, Any]:
    return sample_mcp_raw_multimodal()


@pytest.fixture
def mock_mcp_raw_error() -> dict[str, Any]:
    return sample_mcp_raw_error()


@pytest.fixture
def fake_encoder() -> MagicMock:
    enc = MagicMock()
    enc.encode.side_effect = lambda texts: [[0.1] * 8 for _ in (texts if isinstance(texts, list) else [texts])]
    return enc


@pytest.fixture
def memory_manager(config: dict[str, Any]) -> Any:
    cls = import_class("MemoryManager")
    rag_cfg = config.get("rag_agent", {}) or {}
    return cls(
        long_term_collection=None,
        sqlite_conn=None,
        qdrant_collection=None,
        config=rag_cfg.get("memory", rag_cfg),
    )


@pytest.fixture
def context_manager(config: dict[str, Any]) -> Any:
    cls = import_class("ContextManager")
    return cls(config=config.get("rag_agent", {}))


@pytest.fixture
def planner_agent(config: dict[str, Any]) -> Any:
    cls = import_class("PlannerAgent")
    rag_cfg = config.get("rag_agent", {}) if isinstance(config, dict) else {}
    for kwargs in (
        {"config": rag_cfg},
        {"config": config},
    ):
        try:
            return cls(**kwargs)
        except TypeError:
            continue
    pytest.skip("agent_rag.agents.PlannerAgent: __init__ not implemented per tech_doc §4")


@pytest.fixture
def evaluator(config: dict[str, Any]) -> Any:
    cls = import_class("Evaluator")
    for kwargs in (
        {"config": config.get("rag_agent", {})},
        {"config": config},
        {},
    ):
        try:
            return cls(**kwargs)
        except TypeError:
            continue
    pytest.skip("Evaluator: no compatible __init__ signature")


@pytest.fixture
def generator(config: dict[str, Any]) -> Any:
    cls = import_class("Generator")
    for kwargs in (
        {"config": config.get("rag_agent", {})},
        {"config": config},
        {},
    ):
        try:
            return cls(**kwargs)
        except TypeError:
            continue
    pytest.skip("Generator: no compatible __init__ signature")


@pytest.fixture
def mcp_client(mock_mcp_session: MagicMock, config: dict[str, Any]) -> Any:
    cls = import_class("McpClient")
    return cls(session=mock_mcp_session, config=config.get("rag_agent", {}))


@pytest.fixture
def executor(mcp_client: Any, config: dict[str, Any]) -> Any:
    cls = import_class("Executor")
    return cls(mcp_client=mcp_client, config=config.get("rag_agent", {}))


@pytest.fixture
def orchestrator(config: dict[str, Any]) -> Any:
    cls = import_class("RagOrchestrator")
    return cls(config=config)


# ---------------------------------------------------------------------------
# Real API fixture（用于 @pytest.mark.llm_live 测试）
# ---------------------------------------------------------------------------


def _agent_rag_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _settings_yaml_path() -> Path:
    return _agent_rag_root() / "config" / "settings.yaml"


def _resolve_mcp_stdio(config: dict[str, Any]) -> dict[str, Any] | None:
    rag = config.get("rag_agent", {}) or {}
    stdio = (rag.get("mcp") or {}).get("stdio")
    if not isinstance(stdio, dict) or not stdio.get("command"):
        return None
    out = dict(stdio)
    cwd = out.get("cwd")
    if cwd and not Path(str(cwd)).is_absolute():
        candidates = [
            (_agent_rag_root() / cwd).resolve(),
            (_REPO_ROOT / "mcp_rag").resolve(),
        ]
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "src" / "mcp_server" / "server.py").exists():
                out["cwd"] = str(candidate)
                break
        else:
            out["cwd"] = str(candidates[0])
    return out


@pytest.fixture(scope="session")
def session_config() -> dict[str, Any]:
    return _active_config()


@pytest.fixture(scope="session")
def real_llm(session_config: dict[str, Any]) -> Any:
    """真实 LLM 客户端（session 级，供 llm_live 复用）。"""
    api_key = os.environ.get("LLM_API_KEY") or (session_config.get("llm") or {}).get("api_key")
    if not api_key:
        pytest.skip("requires LLM_API_KEY or llm.api_key in settings.yaml")
    try:
        from src.libs.llm.llm_factory import LLMFactory
        from src.core.settings import load_settings

        settings_path = _settings_yaml_path()
        settings = load_settings(settings_path if settings_path.exists() else None)
        return LLMFactory.create(settings)
    except Exception as e:
        pytest.skip(f"real_llm creation failed: {e}")


@_async_fixture
async def real_mcp_client(config: dict[str, Any]) -> Any:
    """真实 MCP 客户端（与 async 测试共用同一 event loop）。"""
    from contextlib import AsyncExitStack

    stdio = _resolve_mcp_stdio(config)
    if not stdio:
        pytest.skip("rag_agent.mcp.stdio not configured in settings.yaml")
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        pytest.skip("mcp SDK not installed")

    params = StdioServerParameters(
        command=str(stdio.get("command", "python")),
        args=list(stdio.get("args") or []),
        env={**os.environ, **(stdio.get("env") or {})},
        cwd=stdio.get("cwd"),
    )
    rag_cfg = config.get("rag_agent", {}) or {}
    stack = AsyncExitStack()
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    cls = import_class("McpClient")
    client = cls(session=session, config=rag_cfg)
    try:
        yield client
    finally:
        try:
            await stack.aclose()
        except RuntimeError:
            pass  # pytest-asyncio + MCP stdio teardown on Windows


@_async_fixture
async def real_executor(real_mcp_client: Any, real_llm: Any, config: dict[str, Any]) -> Any:
    """真实 Executor：McpClient + 真实 LLM 填参。"""
    cls = import_class("Executor")
    rag_cfg = config.get("rag_agent", {}) or {}
    executor = cls(mcp_client=real_mcp_client, config=rag_cfg)
    executor._llm = real_llm
    yield executor
