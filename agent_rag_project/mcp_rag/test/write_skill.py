import os
c = """---
name: mcp-tool-router
description: 为 MODULAR-RAG-MCP-SERVER 项目的知识库路由 MCP 工具。支持两大场景：(1) 学术论文问答（贡献/方法/对比/图表/结果类中文问题），(2) 通用知识库操作（搜索/查看摘要/读取内容/验证证据等)。当用户需要判断调用哪个工具、确定调用顺序、格式化参数时使用。
---

# MCP 工具路由指南（融合版）
本 skill 帮助根据用户意图选择并排序 MCP 工具，覆盖学术问答和通用操作两大场景。

## 一级决策
用户问"解决/方法/对比/Figure/结果" -> 学术场景；问"搜索/查找/文档/摘要" -> 通用场景；问"验证/证据" -> 验证场景。

## 学术问答决策表
| 类型 | 示例问题 | 工具序列 |
|------|---------|---------|
| contribution | "解决什么核心问题" | query_knowledge_hub -> read_chunk -> check_evidence |
| method | "怎么实现的" | query_knowledge_hub -> read_chunk -> get_neighbor_chunks |
| comparison | "与X相比" | search_by_metadata -> query_knowledge_hub -> check_evidence |
| figure_qa | "Figure 2显示" | search_by_metadata(section="Figure 2") -> read_chunk |
| result | "提升多少" | query_knowledge_hub -> read_chunk -> check_evidence |

## 通用操作决策表  
| 意图 | 示例 | 工具 |
|------|------|------|
| 搜索 | "找向量数据库" | query_knowledge_hub(query="向量数据库") |
| 摘要 | "doc_abc讲了什么" | get_document_summary(doc_id="doc_abc") |
| 结构 | "文档大纲" | get_document_outline(doc_id="...") |
| 内容 | "读chunk_123" | read_chunk(chunk_id="chunk_123") |
| 上下文 | "前后内容" | get_neighbor_chunks(before=2, after=2) |
| 集合 | "有哪些数据集" | list_collections() |
| 过滤 | "tag=security" | search_by_metadata(metadata_filters={"tag":"security"}) |
| 验证 | "有证据支持吗" | query_knowledge_hub -> check_evidence |

## 参数速查
query_knowledge_hub: {"query": "关键词", "top_k": 5}
search_by_metadata: {"metadata_filters": {"tag": "x", "section": "Abstract"}}
read_chunk: {"chunk_id": "chunk_xxx"}
check_evidence: {"claim": "声明", "evidence_chunks": ["chunk_1"]}

## 处理原则
1. 中文去疑问词，中英混合保留英文术语+中文翻译  
2. 学术问题必加 get_neighbor_chunks(before=2, after=2)  
3. 学术/事实类必加 check_evidence  
4. need_image: true 时提示查看原文  

## 示例  
学术: "TOPMOST解决什么" -> query_knowledge_hub(query="TOPMOST 解决 核心问题") -> read_chunk -> get_neighbor_chunks -> check_evidence  
通用: "搜索向量数据库" -> query_knowledge_hub(query="向量数据库", top_k=5)  
验证: "验证稀疏检索更快" -> query_knowledge_hub -> check_evidence  

## 参考  
- 工具: src/mcp_server/tools/*.py  
- 数据: data/demo10_clean_eval_multigold/demo10_clean_eval_multigold_seed.jsonl
"""
with open('src/skill/mcp-tool-router.md', 'w', encoding='utf-8') as f:
    f.write(c)
print('Done')
