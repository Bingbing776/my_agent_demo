#!/usr/bin/env python3
"""一键测试所有 MCP 工具（除 query_knowledge_hub）"""
# python test/test_all_tool.py
#!/usr/bin/env python3
"""一键测试所有 MCP 工具（✅ 修复: tools 属性名）"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJECT_ROOT)

results = {}

async def test_tool(tool_name: str, handler_func, **kwargs):
    """通用测试函数"""
    try:
        print(f"\n🔹 测试 {tool_name}...")
        result = await handler_func(**kwargs)
        
        # 🔥 直接打印完整 MCP 返回内容
        print("   ── 完整返回内容 ──")
        for block in getattr(result, "content", []):
            if hasattr(block, "text"):
                print(block.text)  # 完整打印，不截断
            elif hasattr(block, "type"):
                print(f"[{block.type}] {block}")
        
        if hasattr(result, "structuredContent") and result.structuredContent:
            print("\n   ── structuredContent ──")
            import json
            print(json.dumps(result.structuredContent, ensure_ascii=False, indent=2))
        
        print("   ── 返回结束 ──\n")
        
        results[tool_name] = {"success": True, "content": [getattr(b, "text", str(b)) for b in getattr(result, "content", [])]}
        return True
    except Exception as e:
        results[tool_name] = {"success": False, "error": str(e)}
        print(f"   ❌ 失败: {e}")
        return False



async def main():
    print("🚀 MCP 工具批量测试启动...\n")
    
    # ✅ 修复 1: 导入并初始化 ProtocolHandler
    from src.mcp_server.protocol_handler import ProtocolHandler
    handler = ProtocolHandler(server_name="modular-rag-test", server_version="0.1.0")
    
    # 工具列表
    tools_to_test = [
        ("list_collections", {}),
        ("list_documents", {"limit": 3, "collection": "paper"}),
        ("get_document_summary", {"doc_id": "doc_4e6d9b8d4efd6759", "collection": "paper"}),
        ("get_document_outline", {"doc_id": "doc_4e6d9b8d4efd6759", "collection": "paper"}),
        ("read_chunk", {"chunk_id": "9a08dfd1_0001_6c80634a", "collection": "paper"}),
        ("get_neighbor_chunks", {"chunk_id": "9a08dfd1_0001_6c80634a", "collection": "paper", "window": 1}),
        ("search_by_metadata", {
    "query": "TOPMOST", 
    "filters": {"source_path": "2024.acl-demos.4.pdf"},  # source_file → source_path
    "top_k": 2, 
    "collection": "paper"
}),

        ("check_evidence", {"answer": "TOPMOST 主要解决不同 topic models 使用不同数据集的问题", "evidence_chunk_ids": ["9a08dfd1_0001_6c80634a"], "collection": "paper"}),
    ]


    # ✅ 修复 2: 逐个注册并测试（用 handler.tools 不是 handler._tools）
    for tool_name, default_args in tools_to_test:
        try:
            # 动态导入注册函数
            module = __import__(f"src.mcp_server.tools.{tool_name}", fromlist=["register_tool"])
            module.register_tool(handler)  # 注册函数直接传 handler
            
            # ✅ 修复 3: 从 handler.tools 获取 ToolDefinition，再取 .handler
            tool_def = handler.tools.get(tool_name)
            if tool_def and hasattr(tool_def, "handler"):
                await test_tool(tool_name, tool_def.handler, **default_args)
            else:
                results[tool_name] = {"success": False, "error": "Handler not found"}
                print(f"   ⚠️ {tool_name}: 未找到 handler")
                
        except ImportError as e:
            results[tool_name] = {"success": False, "error": f"Import error: {e}"}
            print(f"   ⚠️ {tool_name}: 导入失败")
        except Exception as e:
            results[tool_name] = {"success": False, "error": str(e)}
            print(f"   ❌ {tool_name}: {e}")
    
    # 打印汇总
    print("\n" + "="*60)
    print("📊 测试结果汇总")
    print("="*60)
    
    success_count = sum(1 for r in results.values() if r.get("success"))
    print(f"✅ 成功: {success_count}/{len(results)}\n")
    
    for name, result in results.items():
        status = "✅" if result.get("success") else "❌"
        print(f"{status} {name}")
        if not result.get("success"):
            print(f"   错误: {result.get('error')}")
    
    # 保存报告
    report_file = Path(PROJECT_ROOT) / "logs" / "tool_test_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"summary": {"success": success_count, "total": len(results)}, "details": results}, 
                  f, ensure_ascii=False, indent=2)
    print(f"\n💾 详细报告: {report_file}")


if __name__ == "__main__":
    asyncio.run(main())
