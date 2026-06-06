"""Agent RAG 本地测试 — 默认 fast 配置（settings + llm_live overlay）。"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# 添加 MODULAR 项目到 Python 路径（访问 src 模块）
modular_root = Path(__file__).resolve().parent.parent / "mcp_rag"
if str(modular_root) not in sys.path:
    sys.path.insert(0, str(modular_root))

# Windows 编码设置
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "ignore")

from agent_rag.config_loader import config_mode_label, load_config
from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator


def _use_fast() -> bool:
    # 默认使用完整 settings.yaml，不加载 llm_live overlay
    if os.environ.get("AGENT_RAG_FAST", "").lower() in ("1", "true", "yes"):
        return True
    return False


async def test_zero_config():
    fast = _use_fast()
    verbose = os.environ.get("AGENT_RAG_VERBOSE", "").lower() in ("1", "true", "yes")
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stderr,
        )
        os.environ.setdefault("PYTHONUNBUFFERED", "1")

    config = load_config(fast=fast, verbose=verbose)

    print("=" * 70)
    print("Agent RAG 本地测试")
    print("=" * 70)
    print(f"\n配置模式: {config_mode_label(fast)}")
    if verbose:
        print("  verbose: MCP DEBUG + agent_rag 日志 → stderr")
    if fast:
        print("  (完整 E2E: set AGENT_RAG_FULL=1)")
    else:
        print("  (快速模式: set AGENT_RAG_FAST=1，或不设 AGENT_RAG_FULL)")

    print("\n创建 RagOrchestrator...")
    orchestrator = RagOrchestrator(config=config)

    print("✓ Orchestrator 创建完成")
    print(f"  - Planner: {orchestrator._planner.__class__.__name__}")
    print(f"  - Evaluator: {orchestrator._evaluator.__class__.__name__}")
    print(f"  - Generator: {orchestrator._generator.__class__.__name__}")

    print("\n" + "=" * 70)
    print("开始问答")
    print("=" * 70)

    query = "TOPMOST 主要解决什么问题？"
    print(f"\n问题: {query}")
    eta = "约 1–3 分钟" if fast else "约 10–30 分钟"
    print(f"\n处理中（{eta}，MCP 检索 + 多轮 LLM）...")

    t0 = time.perf_counter()
    try:
        result = await orchestrator.answer(query)
        elapsed = time.perf_counter() - t0

        print("\n" + "=" * 70)
        print(f"回答: （耗时 {elapsed:.1f}s）")
        print("=" * 70)
        print(result["text"])

        trace = getattr(orchestrator._generator, "_inner_trace", None) or []
        if trace:
            print("\n" + "-" * 70)
            print("工具调用记录:")
            print("-" * 70)
            for i, item in enumerate(trace, 1):
                tool = item.get("tool_name", "unknown")
                ok = item.get("ok", False)
                summary = str(item.get("summary", ""))[:100]
                status = "OK" if ok else "FAIL"
                print(f"  [{i}] {tool} [{status}] {summary}")
        else:
            print("\n（无 MCP 工具调用 — 检查 Planner suggested_tool / API Key / MCP 连接）")

        images = result.get("images", [])
        if images:
            print(f"\n附带图片: {len(images)} 张")

        print("\n" + "=" * 70)
        print("✓ 测试完成")
        print("=" * 70)
        return True

    except Exception as e:
        elapsed = time.perf_counter() - t0
        print("\n" + "=" * 70)
        print(f"✗ 测试失败（{elapsed:.1f}s）")
        print("=" * 70)
        print(f"错误: {type(e).__name__}: {e}")

        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_zero_config())
    sys.exit(0 if success else 1)
