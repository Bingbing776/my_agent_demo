"""MCP Server entry point using official MCP SDK.
MCP Server 的启动入口-> 修正日志输出位置-> 预加载重依赖-> 创建 MCP server-> 用 stdio 跑起来
This module implements the MCP server using the official Python MCP SDK
with stdio transport. It ensures stdout only contains protocol messages
while all logs go to stderr.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from src.mcp_server.protocol_handler import create_mcp_server
from src.observability.logger import get_logger

if TYPE_CHECKING:
    pass

# 这个mcp服务的名字和版本号
SERVER_NAME = "modular-rag-mcp-server"
SERVER_VERSION = "0.1.0"


def _redirect_all_loggers_to_stderr() -> None:
    """Redirect all root logger handlers to stderr.
    不要把普通日志打印到 stdout，stdio是专门留给正式协议消息的， stderr用来写日志和报错信息
    MCP stdio transport reserves stdout for JSON-RPC messages.
    Any logging to stdout corrupts the protocol stream.
    """
    import logging as _logging

    root = _logging.getLogger()
    stderr_handler = _logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        _logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    # Replace any existing stream handlers that might point to stdout
    for handler in root.handlers[:]:
        if isinstance(handler, _logging.StreamHandler) and not isinstance(
            handler, _logging.FileHandler
        ):
            root.removeHandler(handler)
    root.addHandler(stderr_handler)


def _resolve_log_level() -> str:
    """Env MODULAR_RAG_LOG_LEVEL overrides settings.observability.log_level."""
    env_level = os.environ.get("MODULAR_RAG_LOG_LEVEL", "").strip()
    if env_level:
        return env_level.upper()
    try:
        from src.core.settings import load_settings

        return (load_settings().observability.log_level or "INFO").upper()
    except Exception:
        return "INFO"


def _preload_heavy_imports() -> None:
    """Eagerly import heavy third-party modules in the **main thread**.
    先把一些很大的库提前加载好
    因为这些库很重，如果等服务已经跑起来、又开了线程之后才第一次加载，有时会卡住
    MCP SDK uses anyio + background threads for stdin/stdout I/O.
    When a tool handler runs ``asyncio.to_thread(fn)``, *fn* executes in
    a new worker thread.  If it tries to ``import chromadb`` (which
    transitively pulls in onnxruntime, numpy, sqlite3 C extensions …),
    that import can deadlock with the stdin-reader thread because both
    compete for Python's global *import lock*.

    Pre-importing here – before anyio spins up its I/O threads – avoids
    the deadlock entirely: subsequent ``import`` statements in worker
    threads simply hit ``sys.modules`` and return immediately.
    """
    # chromadb is the heaviest culprit (onnxruntime, numpy, …)
    try:
        import chromadb  # noqa: F401
        import chromadb.config  # noqa: F401
    except ImportError:
        pass  # optional at install time

    # Internal modules that tools lazy-import inside asyncio.to_thread
    try:
        import src.core.query_engine.query_processor  # noqa: F401
        import src.core.query_engine.hybrid_search  # noqa: F401
        import src.core.query_engine.dense_retriever  # noqa: F401
        import src.core.query_engine.sparse_retriever  # noqa: F401
        import src.core.query_engine.reranker  # noqa: F401
        import src.ingestion.storage.bm25_indexer  # noqa: F401
        import src.libs.embedding.embedding_factory  # noqa: F401
        import src.libs.vector_store.vector_store_factory  # noqa: F401
    except ImportError:
        pass


async def run_stdio_server_async() -> int:
    """Run MCP server over stdio asynchronously.

    Returns:
        Exit code.
    """
    # Import here to avoid import errors if mcp not installed
    import mcp.server.stdio

    # Ensure ALL logging goes to stderr (stdout is reserved for JSON-RPC) 把日志都赶去 stderr
    _redirect_all_loggers_to_stderr()

    # Pre-load heavy deps in main thread to prevent import-lock deadlocks
    # when tool handlers later call asyncio.to_thread().提前加载重模块
    _preload_heavy_imports()
    log_level = _resolve_log_level()
    logger = get_logger(log_level=log_level)
    logger.info("Starting MCP server (stdio transport) with official SDK. log_level=%s", log_level)

    # Create server with protocol handler 真正把服务器对象造出来
    server = create_mcp_server(SERVER_NAME, SERVER_VERSION)

    # Run with stdio transport 让这个服务器开始通过“输入/输出流”跟外部程序通信
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

    logger.info("MCP server shutting down.")
    return 0


def run_stdio_server() -> int:
    """Run MCP server over stdio (synchronous wrapper).

    Returns:
        Exit code.
    """
    # async 内核：适合网络/IO服务
    return asyncio.run(run_stdio_server_async())


def main() -> int:
    """Entry point for stdio MCP server."""
    #  sync 外壳：适合人和脚本直接按一下就启动
    return run_stdio_server()


if __name__ == "__main__":
    sys.exit(main())