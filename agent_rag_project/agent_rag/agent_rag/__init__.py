"""
RAG 产品运行时（tech_doc §1–§7）。

与 ``meta_harness_rag/harness/``（按 tech_doc **写** 本包下的代码）完全分离：
- 记忆 / 上下文 / MCP / Planner / Evaluator / Generator / RagOrchestrator 均在此包内实现
- 禁止从 ``harness`` import 本包；禁止本包 import ``harness``
"""
