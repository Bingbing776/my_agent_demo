"""多轮对话示例：带记忆的连续问答"""
import asyncio
from pathlib import Path

from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.core.settings import load_settings
from src.libs.llm.llm_factory import LLMFactory


async def multi_turn_conversation():
    """多轮对话示例"""

    # 初始化
    settings = load_settings(Path(__file__).parent / "config" / "settings.yaml")
    llm = LLMFactory.create(settings)

    orchestrator = RagOrchestrator(config={})
    orchestrator._planner._llm = llm
    orchestrator._evaluator._llm = llm
    orchestrator._generator._llm = llm
    orchestrator._llm = llm

    # 多轮对话
    session_id = "user_123"  # 用户会话 ID

    questions = [
        "TOPMOST 是什么？",
        "它的主要功能有哪些？",
        "如何安装和使用？",
    ]

    print("=" * 60)
    print("多轮对话示例")
    print("=" * 60)

    for i, question in enumerate(questions, 1):
        print(f"\n[轮次 {i}]")
        print(f"问: {question}")

        # 调用 answer（可以传入 session_id 来保持上下文）
        result = await orchestrator.answer(question, session_id=session_id)

        print(f"答: {result['text'][:200]}...")  # 只显示前 200 字符

        # 记忆系统会自动保存对话历史
        # 上下文管理器会记录本轮的问答
        # 下一轮提问时会利用这些信息

    print("\n" + "=" * 60)
    print("对话结束")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(multi_turn_conversation())
