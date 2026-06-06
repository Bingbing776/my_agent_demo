"""agent_rag 使用示例：完整的 RAG 问答流程"""
import asyncio
from pathlib import Path

from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.core.settings import load_settings
from src.libs.llm.llm_factory import LLMFactory


async def main():
    # 1. 加载配置
    print("=" * 60)
    print("加载配置...")
    print("=" * 60)

    settings_path = Path(__file__).parent / "config" / "settings.yaml"
    settings = load_settings(settings_path)

    # 2. 配置 RAG Agent（包含 MCP server 连接）
    config = {
        "rag_agent": {
            # MCP Server 配置（用于调用外部工具）
            "mcp": {
                "stdio": {
                    "command": "python",
                    "args": ["-m", "src.mcp_server.server"],
                    "cwd": str(Path(__file__).parent.parent / "mcp_rag"),
                }
            },
            # 记忆管理配置
            "memory": {
                "short_term_capacity": 50,
                "threshold": 0.7,
                "top_k_short": 5,
                "top_k_long": 3,
                "top_k_episodic": 2,
            },
            # 上下文管理配置
            "context": {
                "max_entries": 5,
                "top_k": 3,
            },
        }
    }

    # 3. 创建 LLM 客户端
    print("\n创建 LLM 客户端...")
    llm = LLMFactory.create(settings)
    print(f"✓ LLM 类型: {type(llm).__name__}")

    # 4. 创建 RagOrchestrator
    print("\n创建 RagOrchestrator...")
    orchestrator = RagOrchestrator(config=config)

    # 为各个组件注入 LLM（确保使用同一个 LLM 实例）
    orchestrator._planner._llm = llm
    orchestrator._evaluator._llm = llm
    orchestrator._generator._llm = llm
    orchestrator._llm = llm

    print("✓ Orchestrator 初始化完成")
    print(f"  - Planner: {type(orchestrator._planner).__name__}")
    print(f"  - Evaluator: {type(orchestrator._evaluator).__name__}")
    print(f"  - Generator: {type(orchestrator._generator).__name__}")

    # 5. 提问（完整的 RAG 流程）
    print("\n" + "=" * 60)
    print("开始 RAG 问答...")
    print("=" * 60)

    query = "TOPMOST 主要解决什么问题？"
    print(f"\n问题: {query}")
    print("\n处理中...")
    print("  [1] 规划子任务 (Planner)")
    print("  [2] 调用 MCP 工具检索文档")
    print("  [3] 评估检索结果 (Evaluator)")
    print("  [4] 生成最终答案 (Generator)")

    try:
        result = await orchestrator.answer(query)

        # 6. 显示结果
        print("\n" + "=" * 60)
        print("回答:")
        print("=" * 60)
        print(result["text"])

        # 显示图片信息（如果有）
        images = result.get("images", [])
        if images:
            print(f"\n附带图片: {len(images)} 张")
            for i, img in enumerate(images, 1):
                print(f"  [{i}] {img.get('mime_type', 'unknown')} - {img.get('caption', 'no caption')}")

        print("\n" + "=" * 60)
        print("✓ 问答完成")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
