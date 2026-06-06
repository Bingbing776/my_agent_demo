# meta_harness_rag 测试大纲（按编写顺序）

> 对照 `tech_doc.md` §1–§7；**正文按推荐测试编写顺序排列**（与 `tech_doc` §0.1 实现顺序不同：测试优先契约与纯函数，再 Mock，再集成）。  
> 原则：纯函数多测边界；LLM/MCP 用 Mock + 少量集成/E2E；`__init__` 类 1～2 个 smoke 即可。

---

## 0. 测试基础设施（第 0 步，与阶段 1 并行搭建）

| 项 | 内容 |
|----|------|
| 目录 | `tests/contracts/`、`tests/unit/`、`tests/integration/`、`tests/e2e/` |
| `conftest.py` | 共享 fixture：`mock_llm`、`mock_mcp_raw`、`tmp_config`、`fake_encoder` |
| `pytest.ini` markers | `unit` / `integration` / `mcp` / `e2e` / `llm_live` |
| 通用 Mock | `LLMFactory.create`；`DenseEncoder.encode`；Chroma/SQLite/Qdrant 内存或 `tmp_path` |

```ini
# pytest.ini
markers =
    unit: 无外部服务
    integration: 内存 DB / Mock MCP
    mcp: 需要真实 MCP stdio
    e2e: 全链路 answer，慢
    llm_live: 真实 LLM，仅本地
```

---

## 阶段 1：契约测试（`tests/contracts/`）

> **目标**：后续单测/集成只断言「形状」，不在每个文件重复列键名。  
> **前置**：无。

| 序号 | 契约对象 | 必测 | 建议文件 |
|------|----------|------|----------|
| 1.1 | **MCP 归一化 `dict`**（§3.1） | 含 `content`（list）、`isError`（bool）；text 块含 `type`+`text`；image 块含 `type`+`data`+mime；可选 `structuredContent` | `test_mcp_normalized.py` |
| 1.2 | **`EvalResult`**（§5） | 五键：`passed`,`score`,`require_more_tools`,`status`,`issues`；`status`∈{ok,needs_replan,hard_fail} | `test_eval_result.py` |
| 1.3 | **`SubtaskResult`**（§6） | 必填：`task_id`,`status`,`draft_text`,`tool_trace`,`observation_for_replan`；`status`∈{success,failed,needs_replan}；`tool_trace[]` 含 `tool_name`,`ok`,`summary` | `test_subtask_result.py` |
| 1.4 | **`NextActionResult`**（§6） | `action`∈{call_tool,stop,replan}；call_tool 时 `tool_name` 非空 | `test_next_action_result.py` |
| 1.5 | **`GlobalAnswerReadiness`**（§7） | 五键：`sufficient_for_answer`,`need_replan`,`issues`,`observation_for_replan`；可选 `suggested_retrieval_changes` | `test_global_readiness.py` |
| 1.6 | **`AnswerResult`**（§7） | `text` str；`images[]` 每项 `mime_type`+`data`（base64 可解码） | `test_answer_result.py` |

---

## 阶段 2：纯函数与无外部 IO 工具（`tests/unit/`）

> **目标**：不启 LLM/MCP/DB 即可绿。  
> **前置**：阶段 1 契约（可选，便于 assert 形状）。

### 2.1 §1 证据抽取（§1.0，须最先）

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 2.1.1 | `MemoryManager._evidence_body` | `text_snippet` 优先；fallback `text`；皆空→`""` | strip 空白 | 无 |
| 2.1.2 | `MemoryManager._evidence_chunks_from_result` | 多 citation；无 citation 用顶层 `text`；空 body 跳过；空 result→`[]` | `doc_id`→`source` | 预制 result dict |

### 2.2 §6 Generator 文本/图处理（依赖 MCP 归一形状，不启 MCP）

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 2.2.1 | `Generator._collect_images_from_raw` | 从 `content` 抽 image；`data` 空跳过；`mime_type` 统一 | 便利键 `images`；`max_images_per_subtask` | 预制 raw |
| 2.2.2 | `Generator.summarize_mcp_result` | 只拼 text；多块 text 顺序；image→`[含 N 张图]`；`isError`→`[error]` 前缀；超长截断 | 无 text 块 | 预制 raw |
| 2.2.3 | `Generator._format_trace` | 空 list→占位；`tool_name`+`summary` 格式；`inner_trace_max_chars` 截断 | 多步 trace | 预制 trace list |

### 2.3 §5 Evaluator 文本压测（无 LLM）

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 2.3.1 | `Evaluator.to_planner_observation` | 拼接 status/issues；`max_chars` 截断 | 空 eval_result | 固定 EvalResult |

### 2.4 §7 编排层纯拼接（无 LLM/MCP）

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 2.4.1 | `RagOrchestrator._build_final_evidence_bundle` | 按 `task_id` 排序；段含 status/draft/trace/citations；bundle 总长截断 | 缺 `task_id` 保持 append 顺序 | 预制 subtask_results |
| 2.4.2 | `RagOrchestrator._merge_subtask_images` | 按 `data` 去重；`answer_max_images` 上限 | 空列表 | 重复 image dict |
| 2.4.3 | `RagOrchestrator._should_attach_images` | 有图+`attach_images_when_present`；query 关键词表 | 全 False | 配置组合 |
| 2.4.4 | `RagOrchestrator.build_tool_index_text` | 每工具一行 `- name: desc`；覆盖全部 `_tools_by_name` | 描述过长截断 | 预填 cache dict（无需真 list_tools） |

### 2.5 §4 Planner 文件读取（无 LLM）

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 2.5.1 | `PlannerAgent.load_routing_hint` | 缓存二次命中；无路径→`""`；抽 MUST+路由表 | `routing_hint_max_chars` 截断 | 临时 skill 文件 |

---

## 阶段 3：Mock LLM 的 JSON / 文本类方法（`tests/unit/`，`@pytest.mark.unit`）

> **目标**：固定 `llm.chat` 返回值，测解析、校验、回退、硬规则。  
> **前置**：阶段 1 契约；各模块 `__init__` smoke（可与本阶段同文件夹带测）。

| 序号 | 函数 | 必测 | 建议测 | Mock LLM 返回 |
|------|------|------|--------|----------------|
| 3.1 | `Executor.fill_arguments` | 合法 JSON+schema 通过；缺 required 重试后成功；markdown 围栏剥离；用尽抛错 | 超时；非法额外键 | 多轮固定 JSON |
| 3.2 | `PlannerAgent.plan` | 数组解析；每项含 id/description/intent；`suggested_tool` 在 tool_index 内 | 失败→`[]` 或单条澄清任务 | JSON 数组字符串 |
| 3.3 | `PlannerAgent.replan` | 输出同 plan 校验；user 含 observation 节；不含 inputSchema 字段 | observation 超长截断 | JSON 数组 |
| 3.4 | `Evaluator.evaluate` | EvalResult 五键；`needs_replan`⇒`passed=False`；`strict_json` 失败路径；`eval_max_chars` 截断 | quick_rule 已命中则不调 LLM（在 3.5 测） | 单 JSON 对象 |
| 3.5 | `Evaluator.quick_rule_check` | 连续 n 次 `[error]`→hard_fail；未命中→`None` | n=1 | 预制 trace 摘要 |
| 3.6 | `Generator.choose_next_action` | action 枚举；call_tool 时 tool_name∈tool_names；`max_inner_steps` 禁止再 call_tool；`last_eval.needs_replan` 短路 replan | 冷启动 suggested_tool；passed+!require_more_tools→stop | JSON 对象 |
| 3.7 | `Generator.draft_partial_answer` | 返回纯 str；失败回退 `""`/截断 | 超长输出 | 固定文本 |
| 3.8 | `RagOrchestrator._check_global_answer_readiness` | GlobalAnswerReadiness 五键；解析失败→need_replan；need_replan 时 observation 非空 | sufficient 与证据场景 | JSON 对象 |
| 3.9 | `RagOrchestrator._synthesize_final_answer` | 返回 str；LLM 失败→draft 拼接回退 | 证据不足 prompt（6d） | 固定 Markdown 文本 |

**同阶段 smoke `__init__`（各 1～2 例即可）**

| 序号 | 函数 | 必测 |
|------|------|------|
| 3.10 | `Executor.__init__` | 持有 McpClient；内部创建 LLM |
| 3.11 | `PlannerAgent.__init__` | LLM + routing_skill_path |
| 3.12 | `Evaluator.__init__` | eval_system_prompt 非空默认 |
| 3.13 | `Generator.__init__` | `_inner_trace`/`_inner_images` 初始化 |

---

## 阶段 4：Mock MCP（`tests/unit/` + 少量 `tests/integration/`）

> **目标**：§3 通路正确，仍不跑真实 stdio（除非标记 `mcp`）。  
> **前置**：阶段 1.1 MCP 归一契约；3.1 `fill_arguments` 可独立 Mock。

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 4.1 | `McpClient.__init__` | 保存 session/config | — | Mock session |
| 4.2 | `McpClient.call_tool` | text+image 均保留；`isError`；`structuredContent` 透传；参数校验 | 便利键 `images` | Mock `session.call_tool` |
| 4.3 | `Executor.call_tool` | 成功透传；失败重试次数；退避调用 | 重试后成功；超限 | Mock McpClient |
| 4.4 | `Executor.execute_task` | fill→call 全链；fill 失败不 call（`isError`+无 MCP 调用） | 无 suggested_tool | Mock fill+call |

**可选真实 MCP（`@pytest.mark.mcp`）**

| 序号 | 场景 | 必测 |
|------|------|------|
| 4.5 | `query_knowledge_hub` 真调用 | 返回含 text；有图时 content 含 image 块 |

---

## 阶段 5：§1 MemoryManager（`tests/unit/` + `tests/integration/`）

> **顺序对齐 `tech_doc` §0.2**。  
> **前置**：2.1 证据抽取；Mock encode。

| 序号 | 函数 | 必测 | 建议测 | Mock/Fixture |
|------|------|------|--------|--------------|
| 5.1 | `MemoryManager.__init__` | 三句柄注入；`short_term=[]` | 全 None + config 自建 | 假存储 |
| 5.2 | `compute_memory_similarity` | 空 chunks 约定；多 chunk 平均；返回 embedding 列表形状 | encode 失败 | Mock encode |
| 5.3 | `add_short_term` | 字段齐全；无 session_id 自动生成；超容量删最旧 | 空 chunks；score 默认 0.5 | Mock 5.2 |
| 5.4 | `update_access_count` | 0→1；累加；封顶 10 | 缺键 | memory_item |
| 5.5 | `compress_memory` | LLM 成功 (text, emb)；失败→TextRank | 截断 | Mock LLM |
| 5.6 | `compress_short_term` | 多条合并+score | LLM 失败回退 | 多条 item |
| 5.7 | `condition_fn` | ≥threshold→True；否则 False | 时间衰减边界 | 可控 timestamp |
| 5.8 | `delete_short_term` | 删除后列表正确 | 空列表 | — |
| 5.9 | `promote_to_long_term` | 升级+Chroma add+短期删除 | chunks 推导 | Mock Chroma |
| 5.10 | `get_relevant` | 短长期合并 top-k | 仅一种存储 | 预填+Mock encode |
| 5.11 | `retrieve_context` | 调用链；返回 str | 无记忆 | Mock 5.10/5.6 |
| 5.12 | `add_event` | SQLite+Qdrant 双写；event_id 一致 | LLM 失败回退 | tmp DB |
| 5.13 | `query_relevant_events` | session+7 天过滤 | 不足 k 条 | Mock Qdrant |

---

## 阶段 6：§2 ContextManager（`tests/unit/`）

> **前置**：无硬依赖 §1；可与阶段 5 并行。

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 6.1 | `ContextManager.__init__` | `context_window=[]` | 默认 config | — |
| 6.2 | `ContextManager.update_context` | 写入四字段；超 N 删最旧 | 自动 session_id | — |
| 6.3 | `ContextManager.get_context_window` | 最近 n；session 过滤；时间降序 | n>len | 预填 |
| 6.4 | `ContextManager.get_relevant_context` | top-k+LLM 压缩；失败回退 | 空 window | Mock encode+LLM |

---

## 阶段 7：§6 Generator 状态机（`tests/unit/` + `tests/integration/`）

> **前置**：阶段 2.2、3.6、3.7、4.4；阶段 5 的 Evaluator 完整。

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 7.1 | `Generator.reset_subtask_state` | trace/images/计数清零 | run_subtask 开头调用 | 先污染再 reset |
| 7.2 | **`Generator.run_subtask`**（集成） | 见下表「run_subtask 必测清单」 | max_steps 用尽；填参失败步 | Mock Executor+Evaluator |

**`run_subtask` 必测清单（7.2 内逐条 assert）**

- 返回含 `task_id`（= `task["id"]`）及全部 `SubtaskResult` 键
- 每步 MCP 后：`tool_trace` 增一条；`ok == not raw["isError"]`；`summary` 经 `summarize_mcp_result`
- `task["prior_observation"]` 在每次 `execute_task` 前更新
- `quick_rule_check` 命中时跳过 `evaluate` 的 LLM
- `passed and not require_more_tools` → 提前 stop
- `needs_replan` → `status="needs_replan"` 且 `observation_for_replan` 非空
- `citations` 从 `structuredContent` 合并（有则非空）
- `images` 为浅拷贝，不含 base64 进 summary

---

## 阶段 8：§7 RagOrchestrator（`tests/integration/` + `tests/e2e/`）

> **顺序对齐 `tech_doc` §0.1 第 7 步**。  
> **前置**：阶段 1–7 全部；至少 7.2 `run_subtask` 可 Mock。

### 8.1 同步与 MCP 缓存（无完整 answer）

| 序号 | 函数 | 必测 | 建议测 | Mock |
|------|------|------|--------|------|
| 8.1.1 | `RagOrchestrator.__init__` | 构造 §1/§2/§4–§6；**不**建 Executor/session | 注入句柄 | 子模块 Mock/Fake |
| 8.1.2 | `_ensure_tools_cache` | 幂等；填充 `_tools_by_name`；无 session 报错 | 已缓存早退 | Mock session |
| 8.1.3 | `get_input_schema` | 存在→schema；不存在→抛错或 `{}`（写死一种） | — | 预填 cache |

### 8.2 终稿链路单测（Mock 子模块，仍属 integration）

| 序号 | 函数 | 必测 | 备注 |
|------|------|------|------|
| 8.2.1 | `_build_final_evidence_bundle` | 已在 2.4.1；此处用**真实** SubtaskResult 列表再测一轮 | 集成数据 |
| 8.2.2 | `_check_global_answer_readiness` | 已在 3.8 | — |
| 8.2.3 | `_synthesize_final_answer` | 已在 3.9 | — |
| 8.2.4 | `_merge_subtask_images` / `_should_attach_images` | 已在 2.4.2–2.4.3 | — |

### 8.3 `answer` 集成 / E2E（`@pytest.mark.e2e` 或 `mcp`）

| 序号 | 场景 | 必测 assert |
|------|------|-------------|
| 8.3.1 | **Happy path** | `retrieve_context`+`get_relevant_context` 被调；`plan`→`run_subtask`→门禁通过→`synthesize`；返回 `AnswerResult` 含非空 `text` |
| 8.3.2 | **子任务 needs_replan** | `replan` 被调；`observation` 含 `result["observation_for_replan"]`；新任务入队 |
| 8.3.3 | **全局门禁失败→全局 replan** | 先不合成；`readiness["observation_for_replan"]` 入主 observation；`global_replan_round` 递增；再跑子任务 |
| 8.3.4 | **全局 replan 轮次用尽** | `allow_final_on_insufficient_evidence` 两分支（合成带不足说明 / 固定文案） |
| 8.3.5 | **写回记忆与对话** | `add_short_term`+`update_context`；同一 `session_id` |
| 8.3.6 | **多模态** | 有图时 `AnswerResult.images` 非空且 `_should_attach_images` 为 True（若配置开启） |
| 8.3.7 | **MCP 生存期**（负向） | 退出 `async with` 后 `call_tool` 失败 |

---

## 阶段 9：跨模块场景回归（在 8.3 之后或与之合并）

> 与阶段 8.3 一一对应，便于 checklist。

| 序号 | 场景 | 覆盖阶段 | 断言要点 |
|------|------|----------|----------|
| 9.1 | I1 子任务内循环 | 7.2 | trace 累积 + 提前 stop |
| 9.2 | I2 子任务 needs_replan | 7.2 + 8.3.2 | replan 收到 observation |
| 9.3 | I3 全局门禁→replan | 8.3.3 | 未通过前不默认合成终稿 |
| 9.4 | I4 全局门禁通过 | 8.3.1 | `_synthesize_final_answer` 被调 |
| 9.5 | I5 多模态 | 2.2.1 + 7.2 + 8.3.6 | 图不进 evaluate 摘要 |
| 9.6 | I6 citations 链路 | 4.2 + 7.2 + 2.4.1 | structuredContent→证据包 |
| 9.7 | I7 session 一致 | 5.3 + 6.2 + 8.3.5 | 同源 session_id |
| 9.8 | I8 MCP 会话关闭 | 8.3.7 | 负向 |

---

## 阶段 10：非功能（可选，CI 默认跳过）

| 序号 | 类型 | 测什么 |
|------|------|--------|
| 10.1 | 配置 | `settings.yaml` 加载合并后各 `__init__` 不抛错 |
| 10.2 | 截断 | 各 `*_max_chars` 超限仍不崩 |
| 10.3 | 日志 | JSON 解析失败、bundle 截断有 log（caplog） |
| 10.4 | 真实 LLM | `@pytest.mark.llm_live` 抽样，不进默认 CI |

---

## 附录 A：与 `tech_doc` §0.1 **实现顺序**对照

| 实现顺序（写代码） | 对应测试阶段（写测试） |
|--------------------|------------------------|
| §1 MemoryManager | 阶段 5（依赖阶段 2.1） |
| §2 ContextManager | 阶段 6 |
| §3 McpClient → Executor | 阶段 4（依赖阶段 1.1、3.1） |
| §4 Planner | 阶段 2.5 + 3.2–3.3 |
| §5 Evaluator | 阶段 2.3 + 3.4–3.5 |
| §6 Generator | 阶段 2.2 + 3.6–3.7 + **7** |
| §7 RagOrchestrator | 阶段 2.4 + 3.8–3.9 + **8** |

---

## 附录 B：不必每函数堆砌用例

| 类型 | 策略 |
|------|------|
| 仅赋值 `__init__` | 1～2 smoke |
| `McpClient.call_tool` vs `Executor.call_tool` | 避免重复测透传，合并到 4.3 |
| LLM 判定 | 固定 Mock 输出测分支，不做 prompt 快照 |
| 真实 LLM 质量 | 独立 `eval/` 人工集 |

---

*文档版本：按测试编写顺序编排；与 `tech_doc.md` 对齐。*
