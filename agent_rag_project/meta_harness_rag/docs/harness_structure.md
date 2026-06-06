# Harness 代码目录结构

> `meta_harness_rag` 实现 Harness 三 Agent（Planner / Generator / Evaluator），与 `agent_rag/` 产品代码分离。

## 总览

```text
meta_harness_rag/
├── main.py                          # 入口
├── config/
│   └── harness.yaml                 # Harness 专用配置（含 llm 段，与 agent_rag 无关）
├── core/
│   └── harness_controller.py        # 外层：Planner 队列 → Generator 子任务 → Evaluator
├── docs/
│   ├── tech_doc.md                  # 实现规格
│   ├── harness_structure.md         # 本文件
│   ├── harness.md
│   └── harness_architecture.md
└── harness/                         # Harness 运行时
    ├── types.py                     # HarnessTask / HarnessEvalResult 等
    ├── config_loader.py
    ├── llm_config.py                # 仅读 harness.yaml 的 llm 段
    ├── llm_client.py                # LLMFactory 实例化（Planner/Generator/Evaluator 共用）
    ├── llm_http.py                  # Custom HTTP + 原生 tools（Evaluator FC）
    ├── llm_helpers.py
    ├── project_context.py           # Generator 只读代码快照
    ├── test_index.py                # TEST_INDEX.md 解析与维护
    ├── test_changelog.py            # TEST_CHANGELOG.md：Evaluator 改测试时追加 diff 记录
    │
    ├── planner/                     # Planner Agent（LangGraph）
    │   ├── __init__.py
    │   ├── agent.py                 # HarnessPlanner 门面
    │   ├── graph.py                 # plan / replan 状态图
    │   ├── runtime.py               # 图节点：解析、enrich、replan
    │   ├── state.py                 # PlannerPlanState / PlannerReplanState
    │   └── parsing.py               # tech_doc 规则解析、路径推断、extract_spec_excerpt
    │
    ├── generator/                   # Generator Agent（LangGraph）
    │   ├── __init__.py
    │   ├── agent.py                 # HarnessGenerator 门面
    │   ├── graph.py                 # 子任务内层图：implement ↔ evaluate
    │   ├── runtime.py               # 图节点：实现草稿、调用 Evaluator
    │   └── state.py                 # GeneratorSubtaskState
    │
    └── evaluator/                   # Evaluator Agent（LangGraph）
        ├── __init__.py
        ├── agent.py                 # HarnessEvaluator 门面
        ├── graph.py                 # evaluate 主图
        ├── runtime.py               # 图节点：规则、pytest、写测试、LLM 终判
        ├── state.py                 # EvaluatorState
        ├── tools.py                 # FC 沙箱：read_file / list_dir / grep_in_file
        └── function_calling.py      # 原生 tools + JSON 回退
```

## 三 Agent LangGraph 流程

### Planner — `harness/planner/graph.py`

**plan 图**（`plan()` 一次调用）：

```text
load_doc → parse_tasks → enrich_tasks → finalize_plan → END
```

- `parse_tasks`：规则解析 `docs/tech_doc.md`（无 LLM）
- `enrich_tasks`：可选 LLM 批量补充 description / done_criteria

**replan 图**（`replan(observation)`）：

```text
llm_replan → (有结果? append : fallback_replan) → append_replan → END
```

### Generator — `harness/generator/graph.py`

**子任务内层图**（每个子任务 `run_subtask(task, evaluator)`）：

```text
implement → evaluate → implement → … → END
                      ↘ success / needs_replan / failed（步数用尽）
```

- `implement`：LLM 生成实现草稿
- `evaluate`：调用 `HarnessEvaluator.evaluate()`

### Evaluator — `harness/evaluator/graph.py`

**evaluate 图**（`evaluate(task, trace, draft)`）：

```text
quick_rule → apply_index → assess_ensure_tests → rule_evaluate → llm_evaluate → END
```

- `assess_ensure_tests`：原生 FC 读测试文件，必要时写/改测试
- `rule_evaluate`：`pytest` 单文件

## 共享基础设施

| 模块 | 用途 |
|------|------|
| `harness.yaml` → `llm` | 三 Agent 共用 API（`provider` / `model` / `base_url` / `api_key`） |
| `llm_client.py` | `LLMFactory.create()` → Planner / Generator 普通 `chat` |
| `llm_http.py` | Evaluator function calling（`tools` + `tool_calls`） |
| `test_index.py` | `agent_rag/test/TEST_INDEX.md` 索引 |

## 与 `agent_rag/` 的边界

| 目录 | 职责 |
|------|------|
| `meta_harness_rag/harness/` | 写代码 Harness（本仓库） |
| `agent_rag/agent_rag/` | RAG 产品实现（§1–§7） |
| `agent_rag/test/` | 产品 pytest + `TEST_INDEX.md` / `TEST_PROGRESS.md` / `TEST_CHANGELOG.md` |

Harness **不 import** `agent_rag` 业务模块；仅读写其路径下的文件与跑 pytest。

## 对外导入（不变）

```python
from harness.planner import HarnessPlanner
from harness.generator import HarnessGenerator
from harness.evaluator import HarnessEvaluator
```

## 配置要点（`config/harness.yaml`）

```yaml
llm:
  provider: "custom"
  base_url: "https://..."    # 完整 endpoint（Evaluator HTTP / CustomLLM 语义）
  model: "..."
  api_key: "..."

planner:
  use_llm: true
  enrich_descriptions: true

generator:
  max_inner_steps: 8

evaluator:
  fc_mode: auto              # 原生 FC 优先，可回退 JSON
  llm_transport: custom_http
  fc_read_file_max_chars: 0  # 0=Evaluator 送入 LLM 的正文不截断（索引/草稿/pytest/FC 等同理）
```
