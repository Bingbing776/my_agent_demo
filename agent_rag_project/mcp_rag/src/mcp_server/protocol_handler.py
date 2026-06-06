"""MCP Protocol Handler for JSON-RPC 2.0 message handling.
负责管理 MCP 服务器里有哪些工具，以及别人调用工具时怎么处理。
工具注册 + 工具分发 + 错误处理 的中间层
This module provides the ProtocolHandler class that encapsulates:
- Tool registration and schema management
- JSON-RPC error code handling
- Capability negotiation during initialize
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from mcp import types
from mcp.server.lowlevel import Server

from src.observability.logger import get_logger


# JSON-RPC 2.0 Error Codes 这里放的是一些标准错误码
class JSONRPCErrorCodes:
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


@dataclass
class ToolDefinition:
    """Definition of an MCP tool.一条工具定义，工具登记表"""

    name: str  # 工具名字
    description: str  # 工具说明
    input_schema: Dict[str, Any]  # 输入参数长什么样
    handler: Callable[..., Any]  # 真正执行工具的函数


@dataclass
class ProtocolHandler:
    """Handles MCP protocol operations including tool registration and execution.
    MCP工具总结 管理工具注册表 收到调用时找到正确工具并执行
    This class encapsulates:
    - Tool registration with schema validation
    - Tool execution with error handling
    - Capability declaration for initialize response

    Attributes:
        server_name: Name of the MCP server.
        server_version: Version string of the server.
        tools: Registry of available tools.
    """

    server_name: str
    server_version: str
    tools: Dict[str, ToolDefinition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize logger after dataclass initialization.
        创建一个 logger。这样后面注册工具、执行工具、报错时都能记日志"""
        self._logger = get_logger(log_level="INFO")

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool with the protocol handler.
        把一个工具登记到 self.tools 里
        Args:
            name: Unique name for the tool.
            description: Human-readable description of what the tool does.
            input_schema: JSON Schema for the tool's input parameters. 该工具输入参数的JSON模式。
            handler: Async function that executes the tool logic.执行工具逻辑的异步函数。

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        # 检查是否重名
        if name in self.tools:
            raise ValueError(f"Tool '{name}' is already registered")
        
        # 把工具存进字典
        self.tools[name] = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        # 记日志
        self._logger.info("Registered tool: %s", name)

    def get_tool_schemas(self) -> List[types.Tool]:
        """Get list of tool schemas for tools/list response.
    把当前所有注册好的工具，整理成 MCP 能认识的 Tool 列表，告诉外部我这里有哪些工具，它们叫什么、干什么、输入参数怎么写
        Returns:
            List of Tool objects with name, description, and inputSchema.
        """
        return [
            types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema,
            )
            for tool in self.tools.values()
        ]

    async def execute_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> types.CallToolResult:
        """Execute a registered tool by name.
        根据工具名字找到对应 handler，执行它，并把结果包装成 MCP 能返回的格式
        Args:
            name: Name of the tool to execute.
            arguments: Arguments to pass to the tool handler.

        Returns:
            CallToolResult with content blocks or error indication.

        Raises:
            ValueError: If tool is not found.
        """
        # 先看工具在不在,没找到就返回结构化错误响应
        if name not in self.tools:
            self._logger.warning("Tool not found: %s", name)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Error: Tool '{name}' not found",
                    )
                ],
                isError=True,
            )
        # 找到工具并执行
        tool = self.tools[name]
        try:
            self._logger.info("Executing tool: %s", name)
            result = await tool.handler(**arguments)

            # Handle different return types
            # 如果 handler 已经返回了 types.CallToolResult
            if isinstance(result, types.CallToolResult):
                return result
            # 如果 handler 返回的是字符串
            if isinstance(result, str):
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=result)],
                    isError=False,
                )
            # 如果 handler 返回的是列表就认为这已经是 content blocks 列表
            if isinstance(result, list):
                return types.CallToolResult(content=result, isError=False)
            # Default: convert to string
            # 其他就强行转成字符串再包进 TextContent
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(result))],
                isError=False,
            )

        except TypeError as e:
            # Invalid parameters
            self._logger.error("Invalid params for tool %s: %s", name, e)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Error: Invalid parameters - {e}",
                    )
                ],
                isError=True,
            )
        except Exception as e:
            # Internal error - don't leak stack trace
            self._logger.exception("Internal error executing tool %s", name)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Error: Internal server error while executing '{name}'",
                    )
                ],
                isError=True,
            )

    def get_capabilities(self) -> Dict[str, Any]:
        """Get server capabilities for initialize response.
        告诉客户端，这个 server 有哪些能力
        Returns:
            Dictionary of server capabilities.
        """
        return {
            "tools": {} if self.tools else {},
        }


def _register_default_tools(protocol_handler: ProtocolHandler) -> None:
    """Register all default MCP tools with the protocol handler.
    把系统默认内置的几个工具注册进去
    Args:
        protocol_handler: ProtocolHandler instance to register tools with.
    """
    # Import and register query_knowledge_hub tool
    from src.mcp_server.tools.query_knowledge_hub import register_tool as register_query_tool
    register_query_tool(protocol_handler)
    
    # Import and register list_collections tool
    from src.mcp_server.tools.list_collections import register_tool as register_list_tool
    register_list_tool(protocol_handler)
    
    # Import and register get_document_summary tool
    from src.mcp_server.tools.get_document_summary import register_tool as register_summary_tool
    register_summary_tool(protocol_handler)

    from src.mcp_server.tools.read_chunk import register_tool as register_read_chunk_tool
    register_read_chunk_tool(protocol_handler)

    from src.mcp_server.tools.get_neighbor_chunks import register_tool as register_neighbor_chunks_tool
    register_neighbor_chunks_tool(protocol_handler)

    from src.mcp_server.tools.list_documents import register_tool as register_documents_tool
    register_documents_tool(protocol_handler)

    from src.mcp_server.tools.search_by_metadata import register_tool as register_filtered_search_tool
    register_filtered_search_tool(protocol_handler)

    from src.mcp_server.tools.get_document_outline import register_tool as register_document_outline_tool
    register_document_outline_tool(protocol_handler)

    from src.mcp_server.tools.check_evidence import register_tool as register_check_evidence_tool
    register_check_evidence_tool(protocol_handler)

    from src.mcp_server.tools.get_document_full_text import (
        register_tool as register_document_full_text_tool,
    )
    register_document_full_text_tool(protocol_handler)


def create_mcp_server(
    server_name: str,
    server_version: str,
    protocol_handler: Optional[ProtocolHandler] = None,
    register_tools: bool = True,
) -> Server:
    """Create and configure an MCP server with the protocol handler.
    真正创建一个 MCP SDK 的 Server，并把工具列表和工具调用逻辑挂上去。
    This factory function creates a low-level MCP Server instance and
    registers the necessary handlers for tools/list and tools/call.

    Args:
        server_name: Name of the server.
        server_version: Version string.
        protocol_handler: Optional pre-configured protocol handler.
            If None, a new one will be created.
        register_tools: Whether to register default tools (default: True).

    Returns:
        Configured Server instance ready to run.
    """
    # 如果没传 protocol_handler，就自己创建一个
    if protocol_handler is None:
        protocol_handler = ProtocolHandler(
            server_name=server_name,
            server_version=server_version,
        )

    # Register default tools if requested 如果允许，就注册默认工具
    if register_tools:
        _register_default_tools(protocol_handler)

    # Create low-level server 创建底层 server用的官方 SDK 的 server 类
    server = Server(server_name)

    # Register tools/list handler 注册 tools/list handler
    @server.list_tools()
    async def handle_list_tools() -> List[types.Tool]:
        """Handle tools/list request.当外部请求“列出所有工具”时就调用 protocol_handler.get_tool_schemas(),让外部知道有哪些工具可以调用"""
        return protocol_handler.get_tool_schemas()

    # Register tools/call handler注册 tools/list handler
    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: Dict[str, Any]
    ) -> types.CallToolResult:
        """Handle tools/call request.当外部请求“调用某个工具”时就交给 ProtocolHandler.execute_tool(...)"""
        return await protocol_handler.execute_tool(name, arguments)

    # Store protocol handler on server for access 把 protocol_handler 挂到 server 身上
    server._protocol_handler = protocol_handler  # type: ignore[attr-defined]

    return server


def get_protocol_handler(server: Server) -> ProtocolHandler:
    """Get the protocol handler from a server instance.
    反向取回，如果这个 server 是通过 create_mcp_server() 创建的，那我就能从它身上把 protocol handler 拿回来
    Args:
        server: Server instance created by create_mcp_server.

    Returns:
        The ProtocolHandler associated with the server.

    Raises:
        AttributeError: If server was not created with create_mcp_server.
    """
    return server._protocol_handler  # type: ignore[attr-defined]
