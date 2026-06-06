"""Agent RAG 完整测试 - 真实 LLM + MCP"""
import asyncio
import sys
from pathlib import Path

# Windows 编码设置
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "ignore")

from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.libs.llm.llm_factory import LLMFactory
from src.core.settings import load_settings


async def test_full_rag():
    """完整的 RAG 问答测试"""

    print("=" * 70)
    print("Agent RAG 完整测试")
    print("=" * 70)

    # 1. 加载配置
    print("\n[步骤 1] 加载配置...")
    settings_path = Path(__file__).parent / "config" / "settings.yaml"
    settings = load_settings(settings_path)
    print("✓ 配置加载完成")

    # 2. 创建 LLM
    print("\n[步骤 2] 创建 LLM 客户端...")
    llm = LLMFactory.create(settings)
    print(f"✓ LLM 类型: {type(llm).__name__}")

    # 3. 配置 MCP
    print("\n[步骤 3] 配置 MCP Server...")
    mcp_root = Path(__file__).parent.parent / "mcp_rag"
    print(f"   MCP 根目录: {mcp_root}")

    config = {
        "rag_agent": {
            "mcp": {
                "stdio": {
                    "command": "python",
                    "args": ["-m", "src.mcp_server.server"],
                    "cwd": str(mcp_root),
                }
            },
            "memory": {
                "short_term_capacity": 50,
            },
        }
    }
    print("✓ MCP 配置完成")

    # 4. 创建 Orchestrator
    print("\n[步骤 4] 创建 RagOrchestrator...")
    orchestrator = RagOrchestrator(config=config)

    # 注入 LLM
    orchestrator._planner._llm = llm
    orchestrator._evaluator._llm = llm
    orchestrator._generator._llm = llm
    orchestrator._llm = llm

    print("✓ Orchestrator 初始化完成")

    # 5. 提问
    print("\n" + "=" * 70)
    print("开始问答")
    print("=" * 70)

    query = "TOPMOST 主要解决什么问题？"
    print(f"\n问题: {query}")
    print("\n处理中（这可能需要 30-60 秒）...")
    print("  - 启动 MCP Server")
    print("  - 规划子任务")
    print("  - 调用工具检索文档")
    print("  - 评估结果")
    print("  - 生成最终答案")

    try:
        result = await orchestrator.answer(query)

        # 6. 显示结果
        print("\n" + "=" * 70)
        print("回答:")
        print("=" * 70)
        print(result["text"])

        # 显示图片信息
        images = result.get("images", [])
        if images:
            print(f"\n附带图片: {len(images)} 张")
            for i, img in enumerate(images, 1):
                mime = img.get("mime_type", "unknown")
                caption = img.get("caption", "no caption")
                print(f"  [{i}] {mime} - {caption}")

        print("\n" + "=" * 70)
        print("✓ 测试成功完成")
        print("=" * 70)

        return result

    except Exception as e:
        print("\n" + "=" * 70)
        print("✗ 测试失败")
        print("=" * 70)
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")

        import traceback
        print("\n完整错误栈:")
        traceback.print_exc()

        return None


if __name__ == "__main__":
    print("\n启动测试...\n")
    result = asyncio.run(test_full_rag())

    if result:
        print("\n" + "=" * 70)
        print("测试结论: Agent RAG 工作正常！")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print("测试失败，请检查上面的错误信息")
        print("=" * 70)
        sys.exit(1)
