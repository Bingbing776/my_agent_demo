"""可运行的示例：不使用真实 MCP，演示核心流程"""
import asyncio
import sys
from pathlib import Path

# 设置 stdout 编码为 utf-8
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "ignore")

from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.libs.llm.llm_factory import LLMFactory
from src.core.settings import load_settings


async def demo_without_mcp():
    """不启动 MCP server 的演示（用 mock 数据）"""

    print("=" * 60)
    print("Agent RAG 使用演示（Mock 模式）")
    print("=" * 60)

    # 1. 加载配置
    print("\n[1] 加载配置...")
    settings_path = Path(__file__).parent / "config" / "settings.yaml"
    settings = load_settings(settings_path)
    print("✓ 配置加载完成")

    # 2. 创建 LLM
    print("\n[2] 创建 LLM 客户端...")
    llm = LLMFactory.create(settings)
    print(f"✓ LLM 类型: {type(llm).__name__}")

    # 3. 创建 Orchestrator（不传入 mcp 配置，避免启动 MCP server）
    print("\n[3] 创建 RagOrchestrator...")
    config = {
        "rag_agent": {
            # 不配置 mcp，避免启动 MCP server
            "memory": {
                "short_term_capacity": 10,
            },
        }
    }
    orchestrator = RagOrchestrator(config=config)

    # 注入 LLM
    orchestrator._planner._llm = llm
    orchestrator._evaluator._llm = llm
    orchestrator._generator._llm = llm
    orchestrator._llm = llm

    print("✓ Orchestrator 初始化完成")
    print(f"  - Planner: {orchestrator._planner.__class__.__name__}")
    print(f"  - Evaluator: {orchestrator._evaluator.__class__.__name__}")
    print(f"  - Generator: {orchestrator._generator.__class__.__name__}")
    print(f"  - Memory: {orchestrator._memory.__class__.__name__}")
    print(f"  - Context: {orchestrator._context.__class__.__name__}")

    # 4. 测试各个组件
    print("\n" + "=" * 60)
    print("测试各组件功能")
    print("=" * 60)

    # 测试 Memory
    print("\n[测试] MemoryManager - 短期记忆")
    orchestrator._memory.add_short_term({
        "query": "什么是 RAG？",
        "text": "RAG 是检索增强生成技术",
        "timestamp": "2024-01-01",
    })
    print(f"✓ 短期记忆条数: {len(orchestrator._memory._short_term_memory)}")

    # 测试 Context
    print("\n[测试] ContextManager - 上下文管理")
    orchestrator._context.update_context(
        query="什么是 RAG？",
        answer="RAG 是检索增强生成技术",
    )
    ctx = orchestrator._context.get_context_window(n=5)
    print(f"✓ 上下文窗口条数: {len(ctx)}")

    # 测试 LLM 调用
    print("\n[测试] LLM - 简单对话")
    from src.libs.llm.base_llm import Message
    messages = [Message(role="user", content="你好，请说 'Hello World'")]
    response = llm.chat(messages)
    print(f"✓ LLM 响应: {response.content[:100]}...")

    print("\n" + "=" * 60)
    print("所有组件测试完成！")
    print("=" * 60)

    print("\n提示:")
    print("  - 如需完整的 MCP 工具调用功能，请运行 example_with_mcp.py")
    print("  - 当前演示仅展示核心组件，不涉及外部工具检索")


if __name__ == "__main__":
    asyncio.run(demo_without_mcp())
