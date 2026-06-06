# agent_rag

**RAG 产品**实现目录（tech_doc §1–§7）。由同级目录 [`meta_harness_rag`](../meta_harness_rag/) 中的 **Harness** 按规格自动生成/维护代码。

## 布局

| tech_doc | 路径 |
|----------|------|
| §1 记忆 | `agent_rag/memory/` |
| §2 上下文 | `agent_rag/context/` |
| §3 MCP | `agent_rag/mcp/` |
| §4–§6 Agent | `agent_rag/agents/` |
| §7 编排 | `agent_rag/orchestrator/` |

## 运行与测试

```bash
cd agent_rag
python main_rag.py          # 产品入口（待实现）
python -m pytest test/contracts -q
```

配置：**`config/settings.yaml`** → `rag_agent:`（及顶层 `llm` / `embedding` / `vector_store` 等）。

规格全文见 **`../meta_harness_rag/docs/tech_doc.md`**。
