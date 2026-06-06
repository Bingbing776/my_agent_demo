"""简化版示例：快速开始"""
import asyncio
from pathlib import Path

from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.core.settings import load_settings
from src.libs.llm.llm_factory import LLMFactory


async def quick_start():
    """最简单的使用方式"""

    # 加载配置
    settings = load_settings(Path(__file__).parent / "config" / "settings.yaml")

    # 创建 Orchestrator
    orchestrator = RagOrchestrator(config={})

    # 创建并注入 LLM
    llm = LLMFactory.create(settings)
    orchestrator._planner._llm = llm
    orchestrator._evaluator._llm = llm
    orchestrator._generator._llm = llm
    orchestrator._llm = llm

    # 提问
    result = await orchestrator.answer("什么是 TOPMOST？")

    # 打印结果
    print(result["text"])

    return result


if __name__ == "__main__":
    result = asyncio.run(quick_start())
    print("\n回答完成！")
