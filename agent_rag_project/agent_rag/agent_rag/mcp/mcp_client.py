class McpClient:
    """MCP 客户端薄适配层，封装底层会话的 call_tool 并归一化返回结构。"""

    def __init__(self, underlying_session=None, config=None, *, session=None):
        """
        初始化 McpClient。

        Args:
            underlying_session: 已 initialize 的 MCP 会话（如 mcp.ClientSession）。
            config: 可选配置 dict（如 call_tool_timeout_sec）；None 或未传时为 {}。
            session: underlying_session 的别名，供 conftest 等兼容调用。
        """
        if underlying_session is None and session is None:
            raise TypeError("McpClient requires underlying_session or session")
        self._session = underlying_session if underlying_session is not None else session
        self._config = config or {}

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """
        将 tools/call 委托给 self._session，并将返回归一化为 Executor 所需的结构。

        归一化后的 dict 至少包含：
        - content (list)：保持 MCP 块顺序，每个元素为 {"type": ..., ...}
          * type=="text"：保留 text
          * type=="image"：保留 data (base64), mimeType
        - isError (bool)
        - 可选的 structuredContent
        - 可选的 images：从 content 中的 image 块抽取，每项 {"data", "mime_type", "index"}
        """
        # 参数校验
        if not name or not isinstance(name, str):
            raise ValueError("Tool name must be a non-empty string")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")

        # 调用底层会话 — 兼容测试中可能传入的同步 mock 对象
        from inspect import iscoroutinefunction

        if iscoroutinefunction(self._session.call_tool):
            result = await self._session.call_tool(name, arguments=arguments)
        else:
            result = self._session.call_tool(name, arguments=arguments)

        # 构建归一化字典
        normalized = {}
        normalized["isError"] = bool(result.isError)

        if hasattr(result, "structuredContent") and result.structuredContent is not None:
            normalized["structuredContent"] = result.structuredContent

        content_list = []
        images = []
        for idx, block in enumerate(result.content):
            # 将块转换为字典，尽量保留 SDK 原始字段
            if hasattr(block, "model_dump"):
                block_data = block.model_dump()
            elif hasattr(block, "__dict__"):
                block_data = dict(block.__dict__)
            else:
                block_type = getattr(block, "type", None) or "text"
                block_data = {"type": block_type, "text": str(block)}

            block_type = block_data.get("type")
            if not block_type:
                block_type = getattr(block, "type", None) or "text"
                block_data["type"] = block_type

            content_list.append(block_data)

            if block_data.get("type") == "image":
                img_data = block_data.get("data", "")
                if img_data:
                    mime = block_data.get("mimeType") or block_data.get("mime_type") or ""
                    images.append({
                        "data": img_data,
                        "mime_type": mime,
                        "index": idx,
                    })

        normalized["content"] = content_list
        if images:
            normalized["images"] = images

        return normalized