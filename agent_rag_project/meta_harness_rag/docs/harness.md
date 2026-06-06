# Harness（写代码）

Harness **不是** RAG 产品的任何一章，也 **不实现** 记忆、上下文、MCP 或用户问答。

它只做一件事：读 `tech_doc.md`，在同级 **`../agent_rag/agent_rag/`** 里**一次实现一个函数**，子任务内 `HarnessGenerator` ↔ `HarnessEvaluator` 循环，完成后清空 Generator 状态。

完整双系统说明见 [`architecture.md`](architecture.md)。**Harness 内部分层、双层循环与各方法流程**见 [`harness_architecture.md`](harness_architecture.md)。

## 与 `agent_rag/` 的关系

| 项 | Harness (`meta_harness_rag`) | RAG 产品 (`agent_rag`) |
|----|------------------------------|------------------------|
| §1–§3 记忆/MCP | 不实现 | `agent_rag/memory`, `context`, `mcp` |
| Planner/Gen/Eval | `harness/*` **Harness** 前缀 | `agent_rag/agents/*` 产品类 |
| §7 编排 | 不实现 | `agent_rag/orchestrator/` |
| 配置 | `config/harness.yaml` | `agent_rag/config/settings.yaml` |

实现产物路径由 `harness.module_paths` 指定（相对 `meta_harness_rag` 包根，默认 `../agent_rag/agent_rag/...`）。

## 三 Agent 与 LLM

| Agent | 类 | LLM 职责 |
|-------|-----|----------|
| **Planner** | `HarnessPlanner` | 规则解析 tech_doc 队列；LLM 批量丰富 `description`；`replan` 修正任务 |
| **Generator** | `HarnessGenerator` | 子任务内写代码草稿（Gen↔Eval） |
| **Evaluator** | `HarnessEvaluator` | 查 **`agent_rag/test/TEST_INDEX.md`** 定位测试；LLM 判完备后改测试并**同步索引**；**门禁 `gate.*`** 跑目录/marker 级 pytest（`milestones` + `harness/gates.py`） |

LLM 仅在 `config/harness.yaml` 的 `llm` 段配置（与 `agent_rag/config/settings.yaml` 分离）。

代码目录见 [harness_structure.md](harness_structure.md)。

Evaluator 默认 **原生 function calling**（`evaluator.fc_mode: native`）：`HarnessCustomHttp` 请求带 `tools`，解析 API 的 `tool_calls`，由 `harness/evaluator/tools.py` 执行读文件。需配置 `llm.base_url`（完整 endpoint，同 CustomLLM）与 `evaluator.llm_transport: custom_http`。

## 运行

```bash
cd meta_harness_rag
python main.py --dry-plan
python main.py --max-tasks 1
```

## 控制流

1. `HarnessPlanner`：从 tech_doc 表格拆 `HarnessTask` 队列，并按 **`milestones.gates`** 插入 **`gate.*` 验收任务**（契约 / 关键集成 / E2E）  
2. `HarnessController`：每次一条 → `run_subtask`（门禁任务只跑 pytest，不写产品代码）  
3. `HarnessGenerator`：只读 tech_doc + **`agent_rag/agent_rag/`** + MCP Server；**只写入** `agent_rag/agent_rag/`  
4. `HarnessEvaluator`：在 **`agent_rag/test/`** 跑 pytest  
