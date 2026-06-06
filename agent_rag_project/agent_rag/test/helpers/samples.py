"""测试用预制数据。

重要原则：
- Mock 返回格式必须基于真实 API 观察，不要凭空假设
- 每次改了 prompt 或调用逻辑后，用 pytest -m llm_live 跑真实 API 验证
- 如果真实 API 返回格式和这里的 sample 不一致，更新 sample 并修改对应的 mock 测试

数据来源：
- sample_mcp_raw_*: 基于真实 MCP server 的 call_tool 返回格式
- sample_rag_queries: 基于 demo10_clean_eval_multigold.jsonl 评测集
- sample_mcp_tool_call_result: 基于真实 query_knowledge_hub 返回
- sample_memory_conversation: 模拟真实多轮对话场景
- sample_subtask_plan: 模拟 PlannerAgent 的真实输出格式

LLM 返回格式注意事项（基于真实观察）：
- LLM 可能在 JSON 外面加解释文字
- LLM 可能用 markdown 围栏包裹 JSON
- LLM 可能返回多余字段
- LLM 偶尔会完全不返回 JSON（需要代码容错处理）
"""
from __future__ import annotations

import base64
from typing import Any


def sample_mcp_raw_text_only() -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": "hello"}],
        "isError": False,
        "structuredContent": {"citations": [{"text_snippet": "cite1", "chunk_id": "c1"}]},
    }


def sample_mcp_raw_multimodal() -> dict[str, Any]:
    png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    return {
        "content": [
            {"type": "text", "text": "see figure"},
            {"type": "image", "data": png, "mimeType": "image/png"},
        ],
        "isError": False,
    }


def sample_mcp_raw_error() -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": "tool failed"}],
        "isError": True,
    }


def sample_eval_result(**overrides: Any) -> dict[str, Any]:
    base = {
        "passed": True,
        "score": 0.9,
        "require_more_tools": False,
        "status": "ok",
        "issues": [],
    }
    base.update(overrides)
    return base


def sample_tool_trace_entry(**overrides: Any) -> dict[str, Any]:
    base = {"tool_name": "query_knowledge_hub", "ok": True, "summary": "hit"}
    base.update(overrides)
    return base


def sample_subtask_result(**overrides: Any) -> dict[str, Any]:
    base = {
        "task_id": "t1",
        "status": "success",
        "draft_text": "draft",
        "tool_trace": [sample_tool_trace_entry()],
        "observation_for_replan": "",
        "citations": [],
        "images": [],
    }
    base.update(overrides)
    return base


def sample_global_readiness(**overrides: Any) -> dict[str, Any]:
    base = {
        "sufficient_for_answer": True,
        "need_replan": False,
        "issues": [],
        "observation_for_replan": "",
        "suggested_retrieval_changes": [],
    }
    base.update(overrides)
    return base


def sample_answer_result(**overrides: Any) -> dict[str, Any]:
    png = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    base = {"text": "final answer", "images": [{"mime_type": "image/png", "data": png}]}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 真实业务场景测试案例（基于 demo10 评测集 + ACL 论文数据）
# ---------------------------------------------------------------------------

def sample_rag_queries() -> list[dict[str, Any]]:
    """覆盖多种题型的 RAG 查询样本，来自 demo10_clean_eval_multigold.jsonl。"""
    return [
        {
            "id": "demo10_clean_q001",
            "query": "TOPMOST 主要解决现有 topic modeling 研究中的什么核心问题？",
            "question_type": "contribution",
            "source_file": "2024.acl-demos.4.pdf",
            "doc_title": "TOPMOST: A Topic Modeling System Toolkit",
            "gold_answer": (
                "TOPMOST 主要解决不同 topic models 使用不同数据集、实现和评估设置，"
                "导致快速使用和公平比较困难的问题。"
            ),
            "relevant_chunk_ids": ["9a08dfd1_0001_6c80634a", "9a08dfd1_0020_85b92940"],
            "evidence_keywords": ["distinct datasets", "implementations", "evaluations", "fair comparisons"],
            "expected_tools": ["query_knowledge_hub", "read_chunk", "get_neighbor_chunks", "check_evidence"],
            "need_table": False,
            "need_image": False,
        },
        {
            "id": "demo10_clean_q003",
            "query": "与 OCTIS 相比，TOPMOST 在 topic modeling 场景覆盖上有什么扩展？",
            "question_type": "comparison",
            "source_file": "2024.acl-demos.4.pdf",
            "doc_title": "TOPMOST: A Topic Modeling System Toolkit",
            "gold_answer": (
                "TOPMOST 除 basic 和 hierarchical 外，还覆盖 dynamic 和 cross-lingual topic modeling，"
                "并补齐对应 datasets、models 和 evaluations。"
            ),
            "relevant_chunk_ids": ["9a08dfd1_0003_f2c0b3c8", "9a08dfd1_0011_dfa7a93b"],
            "evidence_keywords": ["OCTIS", "Basic topic modeling", "Dynamic topic modeling", "Cross-lingual topic modeling"],
            "expected_tools": ["search_by_metadata", "read_chunk", "get_neighbor_chunks", "check_evidence"],
            "need_table": True,
            "need_image": False,
        },
        {
            "id": "demo10_clean_q004",
            "query": "Figure 2 中 TOPMOST 的总体架构强调了哪些模块解耦？",
            "question_type": "figure_qa",
            "source_file": "2024.acl-demos.4.pdf",
            "doc_title": "TOPMOST: A Topic Modeling System Toolkit",
            "gold_answer": (
                "Figure 2 显示 TOPMOST 解耦了 dataset handler/preprocessing、topic model、"
                "trainer 和 evaluation，并覆盖 basic、hierarchical、dynamic、cross-lingual 等场景。"
            ),
            "relevant_chunk_ids": ["9a08dfd1_0008_31066a26"],
            "evidence_keywords": ["Figure 2", "Dataset Handler", "Topic Model", "Trainer", "Evaluation"],
            "expected_tools": ["search_by_metadata", "read_chunk", "get_neighbor_chunks", "check_evidence"],
            "need_table": False,
            "need_image": True,
        },
        {
            "id": "demo10_clean_q005",
            "query": "UMC 论文要解决无监督多模态语义发现中的哪两个核心挑战？",
            "question_type": "contribution",
            "source_file": "2024.acl-long.2.pdf",
            "doc_title": "Unsupervised Multimodal Clustering for Semantics Discovery in Multimodal Utterances",
            "gold_answer": (
                "UMC 关注如何利用非语言模态补充文本模态，"
                "以及如何充分利用无标注多模态数据学习有利于聚类的表示。"
            ),
            "relevant_chunk_ids": ["44513225_0005_93139cc2", "44513225_0011_1eae9f45"],
            "evidence_keywords": ["nonverbal modalities", "complement the text modality", "unlabeled data"],
            "expected_tools": ["query_knowledge_hub", "read_chunk", "get_neighbor_chunks", "check_evidence"],
            "need_table": False,
            "need_image": False,
        },
        {
            "id": "demo10_clean_q009",
            "query": "MAGE 论文为什么认为真实场景中的机器生成文本检测更困难？",
            "question_type": "motivation",
            "source_file": "2024.acl-long.3.pdf",
            "doc_title": "MAGE: Machine-generated Text Detection in the Wild",
            "gold_answer": "",  # 需要从知识库检索
            "relevant_chunk_ids": [],
            "evidence_keywords": [],
            "expected_tools": ["query_knowledge_hub", "read_chunk", "get_neighbor_chunks", "check_evidence"],
            "need_table": False,
            "need_image": False,
        },
    ]


def sample_mcp_tool_call_result() -> dict[str, Any]:
    """模拟 MCP query_knowledge_hub 返回的真实检索结果。"""
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "## 检索结果（Top 3）\n\n"
                    "#01 score=0.0323 chunk_id=9a08dfd1_0014_24dbbf27\n"
                    "source: 2024.acl-demos.4.pdf\n"
                    "text: ## 3.1 Topic Modeling Scenarios and Topic Models\n"
                    "As summarized in Table 2, TOPMOST reaches a wider coverage...\n\n"
                    "#02 score=0.0315 chunk_id=9a08dfd1_0007_2c9d39fa\n"
                    "source: 2024.acl-demos.4.pdf\n"
                    "text: To resolve these issues, we introduce TOPMOST...\n\n"
                    "#03 score=0.0313 chunk_id=9a08dfd1_0033_d9b064d5\n"
                    "source: 2024.acl-demos.4.pdf\n"
                    "text: ## 7 Conclusion and Future Work\n"
                    "In this paper, we present TOPMOST...\n"
                ),
            }
        ],
        "isError": False,
        "structuredContent": {
            "citations": [
                {"text_snippet": "TOPMOST reaches a wider coverage", "chunk_id": "9a08dfd1_0014_24dbbf27"},
                {"text_snippet": "we introduce TOPMOST", "chunk_id": "9a08dfd1_0007_2c9d39fa"},
            ]
        },
    }


def sample_memory_conversation() -> list[dict[str, str]]:
    """模拟多轮对话场景，用于测试 MemoryManager 和 ContextManager。"""
    return [
        {"role": "user", "content": "请帮我查一下 TOPMOST 这个工具的主要功能"},
        {"role": "assistant", "content": "TOPMOST 是一个 topic modeling 系统工具包，覆盖 basic、hierarchical、dynamic 和 cross-lingual 四种场景。"},
        {"role": "user", "content": "它和 OCTIS 相比有什么优势？"},
        {"role": "assistant", "content": "TOPMOST 比 OCTIS 多覆盖了 dynamic 和 cross-lingual topic modeling，并补齐了对应的数据集、模型和评估指标。"},
        {"role": "user", "content": "那 TOPMOST 的架构是怎么设计的？"},
    ]


def sample_subtask_plan() -> list[dict[str, Any]]:
    """模拟 PlannerAgent 针对用户问题生成的子任务列表。"""
    return [
        {
            "task_id": "t1",
            "action": "call_tool",
            "tool_name": "query_knowledge_hub",
            "arguments": {"query": "TOPMOST topic modeling toolkit features"},
            "reason": "检索 TOPMOST 的功能特性",
        },
        {
            "task_id": "t2",
            "action": "call_tool",
            "tool_name": "read_chunk",
            "arguments": {"chunk_id": "9a08dfd1_0001_6c80634a"},
            "reason": "读取 Abstract 段落获取核心信息",
        },
        {
            "task_id": "t3",
            "action": "stop",
            "tool_name": "",
            "arguments": {},
            "reason": "已收集足够证据，可以生成回答",
        },
    ]

