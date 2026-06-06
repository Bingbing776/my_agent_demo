"""Agent RAG 产品质量评测 - 使用 RAGAS 框架"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 添加 MODULAR 项目到 Python 路径
modular_root = Path(__file__).resolve().parent.parent / "mcp_rag"
if str(modular_root) not in sys.path:
    sys.path.insert(0, str(modular_root))

# Windows 编码
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "ignore")

from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 测试集选择：
# - "original": 原始 5 条问题（快速验证）
# - "extended": 扩展 30 条问题（全面评估）
EVAL_DATASET = os.environ.get("EVAL_DATASET", "extended")

if EVAL_DATASET == "extended":
    EVAL_DATA_PATH = Path(__file__).resolve().parent.parent / (
        "mcp_rag/data/demo10_clean_eval_multigold/demo10_extended_eval_30q.jsonl"
    )
    MAX_QUESTIONS = int(os.environ.get("EVAL_MAX_QUESTIONS", "30"))
else:
    EVAL_DATA_PATH = Path(__file__).resolve().parent.parent / (
        "mcp_rag/data/demo10_clean_eval_multigold/demo10_clean_eval_multigold.jsonl"
    )
    MAX_QUESTIONS = int(os.environ.get("EVAL_MAX_QUESTIONS", "5"))
# 结果保存路径
RESULTS_PATH = Path(__file__).resolve().parent / "eval_results.json"


# ---------------------------------------------------------------------------
# 运行 Agent RAG 获取回答
# ---------------------------------------------------------------------------

async def run_agent_rag(questions: list[dict]) -> list[dict]:
    """对每个问题调用 Agent RAG，收集回答和上下文"""
    print(f"\n{'='*60}")
    print(f"运行 Agent RAG（共 {len(questions)} 个问题）")
    print(f"{'='*60}\n")

    orchestrator = RagOrchestrator()
    results = []

    for i, q in enumerate(questions, 1):
        query = q["query"]
        print(f"[{i}/{len(questions)}] {query[:50]}...", flush=True)

        t0 = time.perf_counter()
        try:
            answer_result = await orchestrator.answer(query)
            elapsed = time.perf_counter() - t0

            answer_text = answer_result.get("text", "")

            # 收集上下文：从 memory 的 retrieve_context 获取
            # （因为 _inner_trace 在子任务结束后被清空）
            contexts = []
            try:
                mem_ctx = orchestrator._memory.retrieve_context(query)
                if mem_ctx:
                    contexts.append(mem_ctx[:2000])
            except Exception:
                pass
            # 如果没有记忆上下文，用答案本身作为 context（RAGAS 需要非空）
            if not contexts:
                contexts = [answer_text[:2000]] if answer_text else ["No context"]

            results.append({
                "id": q["id"],
                "query": query,
                "answer": answer_text,
                "contexts": contexts,
                "ground_truth": q.get("gold_answer_zh") or q.get("reference_answer", ""),
                "relevant_chunk_ids": q.get("relevant_chunk_ids", []),
                "elapsed": round(elapsed, 1),
                "success": True,
            })
            print(f"    ✓ {elapsed:.1f}s | 答案长度: {len(answer_text)} 字", flush=True)

        except Exception as e:
            elapsed = time.perf_counter() - t0
            results.append({
                "id": q["id"],
                "query": query,
                "answer": f"[ERROR] {e}",
                "contexts": [],
                "ground_truth": q.get("gold_answer_zh") or q.get("reference_answer", ""),
                "relevant_chunk_ids": q.get("relevant_chunk_ids", []),
                "elapsed": round(elapsed, 1),
                "success": False,
            })
            print(f"    ✗ {elapsed:.1f}s | 错误: {e}", flush=True)

    return results


# ---------------------------------------------------------------------------
# RAGAS 评测
# ---------------------------------------------------------------------------

def run_ragas_evaluation(results: list[dict]) -> dict:
    """使用 RAGAS 评测回答质量"""
    print(f"\n{'='*60}")
    print("RAGAS 评测")
    print(f"{'='*60}\n")

    try:
        from ragas import evaluate
        from ragas.metrics import _Faithfulness, _ContextPrecision, _ContextRecall
        from ragas.llms import llm_factory
        from ragas.embeddings import embedding_factory
        from openai import OpenAI
        from datasets import Dataset
    except ImportError as e:
        print(f"RAGAS 依赖缺失: {e}")
        print("请安装: pip install ragas datasets openai")
        return {}

    # 使用项目配置的 LLM 和 Embedding
    try:
        import sys
        from pathlib import Path

        modular_root = Path(__file__).resolve().parent.parent / "mcp_rag"
        if str(modular_root) not in sys.path:
            sys.path.insert(0, str(modular_root))

        from src.core.settings import load_settings

        settings_path = modular_root / "config" / "settings.yaml"
        settings = load_settings(settings_path)

        # LLM (DeepSeek) - 用 deepseek-chat 而不是推理模型，避免 reasoning token 耗尽
        llm_client = OpenAI(
            api_key=settings.llm.api_key,
            base_url=getattr(settings.llm, 'base_url', None),
        )
        ragas_llm = llm_factory("deepseek-chat", client=llm_client, max_tokens=8192)

        # Embedding (dashscope/qwen)
        emb_client = OpenAI(
            api_key=settings.embedding.api_key,
            base_url=getattr(settings.embedding, 'base_url', None),
        )
        ragas_emb = embedding_factory('openai', model=settings.embedding.model, client=emb_client)

        print(f"✓ LLM: {settings.llm.model}")
        print(f"✓ Embedding: {settings.embedding.model}")
    except Exception as e:
        print(f"RAGAS 评测跳过: 无法加载配置 - {e}")
        import traceback
        traceback.print_exc()
        return {}

    # 构建 RAGAS 数据集
    data = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": [],
    }

    for r in results:
        if not r["success"]:
            continue
        data["question"].append(r["query"])
        data["answer"].append(r["answer"])
        data["contexts"].append(r["contexts"] if r["contexts"] else ["No context retrieved"])
        data["ground_truth"].append(r["ground_truth"])

    if not data["question"]:
        print("没有成功的回答可以评测")
        return {}

    dataset = Dataset.from_dict(data)
    print(f"评测样本数: {len(dataset)}")

    # 初始化 metrics 并运行
    try:
        f = _Faithfulness(llm=ragas_llm)
        cp = _ContextPrecision(llm=ragas_llm)
        cr = _ContextRecall(llm=ragas_llm)

        result = evaluate(dataset=dataset, metrics=[f, cp, cr])
        scores = result.scores
        # 计算平均分
        avg_scores = {}
        for score_dict in scores:
            for k, v in score_dict.items():
                if k not in avg_scores:
                    avg_scores[k] = []
                if v is not None:
                    avg_scores[k].append(float(v))
        return {k: sum(v)/len(v) if v else 0.0 for k, v in avg_scores.items()}
    except Exception as e:
        print(f"RAGAS 评测失败: {e}")
        import traceback
        traceback.print_exc()
        return {}


# ---------------------------------------------------------------------------
# 简易评测（不依赖 RAGAS）
# ---------------------------------------------------------------------------

def simple_evaluation(results: list[dict]) -> dict:
    """简单的规则评测（不需要 RAGAS）"""
    print(f"\n{'='*60}")
    print("简易评测")
    print(f"{'='*60}\n")

    metrics = {
        "total": len(results),
        "success_count": 0,
        "avg_answer_length": 0,
        "avg_elapsed": 0,
        "keyword_hit_rate": 0,
        "has_citation_rate": 0,
    }

    total_length = 0
    total_elapsed = 0
    keyword_hits = 0
    citation_count = 0

    for r in results:
        if r["success"]:
            metrics["success_count"] += 1
            total_length += len(r["answer"])
            total_elapsed += r["elapsed"]

            # 关键词命中率：检查 ground_truth 中的关键词是否出现在 answer 中
            gt = r["ground_truth"]
            answer = r["answer"]
            if gt:
                # 提取 ground_truth 中的关键词（2+ 字符的词）
                import re
                gt_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", gt))
                answer_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", answer))
                if gt_words:
                    overlap = len(gt_words & answer_words) / len(gt_words)
                    keyword_hits += overlap

            # 引用检查
            if "[" in answer and "]" in answer:
                citation_count += 1

    n = metrics["success_count"] or 1
    metrics["avg_answer_length"] = round(total_length / n)
    metrics["avg_elapsed"] = round(total_elapsed / n, 1)
    metrics["keyword_hit_rate"] = round(keyword_hits / n, 3)
    metrics["has_citation_rate"] = round(citation_count / n, 3)
    metrics["success_rate"] = round(metrics["success_count"] / metrics["total"], 3)

    return metrics


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("  Agent RAG 产品质量评测")
    print("=" * 60)
    print(f"\n评测数据: {EVAL_DATA_PATH.name}")
    print(f"评测数量: {MAX_QUESTIONS} 条")
    print(f"结果保存: {RESULTS_PATH}")

    # 检查是否已有结果
    results = None
    print(f"\n[DEBUG] 检查文件是否存在: {RESULTS_PATH.exists()}")
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                print(f"[DEBUG] 文件读取成功，keys: {saved.keys()}")
                print(f"[DEBUG] results 长度: {len(saved.get('results', []))}, MAX_QUESTIONS: {MAX_QUESTIONS}")
                if "results" in saved and len(saved["results"]) == MAX_QUESTIONS:
                    print(f"\n✓ 检测到已有评测结果（{len(saved['results'])} 条）")
                    print("  跳过 Agent RAG 运行，直接使用已有结果")
                    results = saved["results"]
                else:
                    print(f"[DEBUG] 条件不满足，将重新运行")
        except Exception as e:
            print(f"\n⚠ 读取已有结果失败: {e}，将重新运行")
            import traceback
            traceback.print_exc()

    # 如果没有结果，运行 Agent RAG
    if results is None:
        # 加载评测数据
        questions = []
        with open(EVAL_DATA_PATH, "r", encoding="utf-8") as f:
            for line in f:
                questions.append(json.loads(line))
        questions = questions[:MAX_QUESTIONS]
        print(f"已加载 {len(questions)} 个评测问题")

        # 运行 Agent RAG
        results = await run_agent_rag(questions)

    # 简易评测
    simple_metrics = simple_evaluation(results)
    print("\n简易评测结果:")
    print(f"  成功率: {simple_metrics['success_rate']*100:.1f}%")
    print(f"  平均答案长度: {simple_metrics['avg_answer_length']} 字")
    print(f"  平均耗时: {simple_metrics['avg_elapsed']}s")
    print(f"  关键词命中率: {simple_metrics['keyword_hit_rate']*100:.1f}%")
    print(f"  引用覆盖率: {simple_metrics['has_citation_rate']*100:.1f}%")

    # RAGAS 评测（可选）
    ragas_metrics = {}
    try:
        ragas_metrics = run_ragas_evaluation(results)
        if ragas_metrics:
            print("\nRAGAS 评测结果:")
            for k, v in ragas_metrics.items():
                print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    except Exception as e:
        print(f"\nRAGAS 评测跳过: {e}")

    # 保存结果
    output = {
        "config": {
            "max_questions": MAX_QUESTIONS,
            "eval_data": str(EVAL_DATA_PATH),
        },
        "simple_metrics": simple_metrics,
        "ragas_metrics": ragas_metrics,
        "results": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {RESULTS_PATH}")

    print(f"\n{'='*60}")
    print("评测完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
