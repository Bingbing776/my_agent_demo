#!/usr/bin/env python3
"""通过 MCP 协议 (stdio) 测试所有工具是否正常工作。

这是真正的端到端 MCP 测试：
  本脚本 (client) -> stdio 管道 -> MCP server 子进程 -> 执行工具 -> 返回结果

运行方式：
  cd mcp_rag
  python test/test_mcp_stdio.py

需要：
  - pip install mcp (MCP SDK)
  - config/settings.yaml 配置正确 (embedding api_key 等)
  - data/db/chroma 里有数据 (已 ingest 过)
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def main():
    try:
        from mcp.client.stdio import stdio_client
        from mcp import StdioServerParameters, ClientSession
    except ImportError:
        print("❌ 请先安装 MCP SDK: pip install mcp")
        return 1

    print("=" * 60)
    print("🔌 MCP Server 端到端测试（通过 stdio 协议）")
    print("=" * 60)

    # 1. 启动 MCP server 子进程
    print("\n[1/4] 启动 MCP server...")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server.server"],
        cwd=str(PROJECT_ROOT),
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # 2. MCP 握手
                print("[2/4] MCP 协议握手 (initialize)...")
                try:
                    await session.initialize()
                    print("  ✓ 握手成功")
                except Exception as e:
                    print(f"  ❌ 握手失败: {e}")
                    return 1

                # 3. 列出可用工具
                print("[3/4] 获取工具列表 (list_tools)...")
                try:
                    tools_result = await session.list_tools()
                    tool_names = [t.name for t in tools_result.tools]
                    print(f"  ✓ 可用工具 ({len(tool_names)} 个): {', '.join(tool_names)}")
                except Exception as e:
                    print(f"  ❌ list_tools 失败: {e}")
                    return 1

                # 4. 逐个测试工具
                print("[4/4] 测试各工具调用...\n")

                test_cases = [
                    ("list_collections", {}),
                    ("list_documents", {"collection": "paper", "limit": 2}),
                    ("query_knowledge_hub", {"query": "TOPMOST topic modeling", "collection": "paper", "top_k": 3}),
                    ("read_chunk", {"chunk_id": "9a08dfd1_0001_6c80634a", "collection": "paper"}),
                    ("get_neighbor_chunks", {"chunk_id": "9a08dfd1_0001_6c80634a", "collection": "paper", "window": 1}),
                    ("get_document_summary", {"doc_id": "doc_4e6d9b8d4efd6759", "collection": "paper"}),
                    ("get_document_outline", {"doc_id": "doc_4e6d9b8d4efd6759", "collection": "paper"}),
                    ("get_document_full_text", {"doc_id": "doc_4e6d9b8d4efd6759", "collection": "paper"}),
                    ("search_by_metadata", {"query": "TOPMOST", "filters": {"source_path": "2024.acl-demos.4.pdf"}, "top_k": 2, "collection": "paper"}),
                    ("check_evidence", {"answer": "TOPMOST 解决 topic modeling 工具包的问题", "evidence_chunk_ids": ["9a08dfd1_0001_6c80634a"], "collection": "paper"}),
                ]

                results = {}
                for tool_name, arguments in test_cases:
                    if tool_name not in tool_names:
                        print(f"  ⏭️  {tool_name}: 服务端未注册，跳过")
                        results[tool_name] = "skipped"
                        continue

                    try:
                        result = await session.call_tool(tool_name, arguments=arguments)

                        # 检查返回结构
                        has_content = bool(result.content)
                        is_error = getattr(result, "isError", False)

                        if is_error:
                            error_text = result.content[0].text if result.content else "unknown"
                            print(f"  ⚠️  {tool_name}: 工具返回错误 - {error_text[:100]}")
                            results[tool_name] = f"error: {error_text[:100]}"
                        elif has_content:
                            first_block = result.content[0]
                            preview = getattr(first_block, "text", str(first_block))[:80]
                            print(f"  ✓  {tool_name}: {preview}...")
                            results[tool_name] = "success"
                        else:
                            print(f"  ⚠️  {tool_name}: 返回为空")
                            results[tool_name] = "empty"

                    except Exception as e:
                        print(f"  ❌  {tool_name}: {type(e).__name__}: {e}")
                        results[tool_name] = f"exception: {e}"

    except Exception as e:
        print(f"❌ MCP server 启动失败: {e}")
        return 1

    # 汇总
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    success = sum(1 for v in results.values() if v == "success")
    total = len(results)
    print(f"  通过: {success}/{total}")
    for name, status in results.items():
        icon = "✓" if status == "success" else "✗" if "exception" in str(status) else "⚠"
        print(f"  {icon} {name}: {status}")

    return 0 if success == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
