---
name: mcp-tool-router
description: MCP 路由：触发条件→工具顺序、DEFAULT 自排序规则、参数名与 inputSchema 一致；渐进式只加载当前工具 schema。用于 Planner/Agent 选工具与排序。
---

# MCP 工具路由（MODULAR-RAG）

引用：`@src/skill/mcp-tool-router.md`。

## 硬规则（MUST）

1. 各工具参数以 MCP `tools/list` 里该工具的 **`inputSchema`** 为准；本文不重复完整字段表。
2. `search_by_metadata` 过滤对象键名必须是 **`filters`**（禁止 `metadata_filters`）。
3. `get_neighbor_chunks` 用 **`window`**（0–5），禁止 `before`/`after`。
4. `check_evidence` 用 **`answer`** + **`evidence_chunk_ids`**（禁止 `claim`/`evidence_chunks`）。
5. `query_knowledge_hub` / `search_by_metadata` 返回已含 **`chunk_id`+正文** 时，**不得**仅为阅读同批命中块再调 `read_chunk`；缺块、要全 metadata、或 `allow_partial_match` 定位时才 `read_chunk`。
6. **`get_document_full_text`**：仅当**已锁定单篇文档**（已知 **`doc_id`** / `source_ref`，或 `filters` 能唯一确定一篇）且需要**整篇正文**（综合性复述、全文脉络、通读后作答）时使用；**不得**对多篇文档连续调用以拼「跨库全文」；跨文档综合性问题**先**用检索链定位多篇，再**按需**对 **1~2 篇最关键** 文档调全文（其余用 hub 命中 + `get_neighbor_chunks`）。
7. Host：**Planner** 上下文里工具区只用 **`tools/list` 压成的「name + description 一行」表**（**不含**各工具 `inputSchema`）供选名/排序；**已定 `tool_name` 之后**，才把**该工具**的 `inputSchema` 交给填参模型或执行器（每步一份，不叠放其它工具 schema）。

## 主路由表（自上而下匹配第一行）

| 触发条件（命中一行即采用） | 工具顺序（`→` 有序；`[]` 内为按需） |
|---------------------------|--------------------------------------|
| 用户要列库 / 集合 | `list_collections` →（按需）`list_documents` |
| **单篇文档综合性问题**（已锁定一篇：全文概括、通读综合、按文档整体作答；含「这篇论文整体…」「该文档从头到尾…」「summarize this document」） | 已知 `doc_id`：**[`get_document_summary`] → [`get_document_outline`] →** `get_document_full_text`（`filters`/`doc_id` 收窄）→ [`check_evidence`]。未知 `doc_id`：先 `search_by_metadata` 或 `query_knowledge_hub`（`filters` 尽量收窄到单篇）**定 doc** → 再 `get_document_full_text` → [`check_evidence`]。**勿**用 top-k 检索碎片代替全文综合。 |
| **跨多篇文档综合性问题**（对比多篇、领域综述、跨论文趋势、需多源整合；含「几篇/多篇/对比 A 与 B」「ACL 2024 整体趋势」） | `query_knowledge_hub` 和/或 `search_by_metadata`（多 doc 检索）→ [`list_documents` 若需枚举范围] → 对 **Top 命中中的 1~2 篇关键文档** 可选 `get_document_summary` / [`get_document_full_text` 仅最关键 1 篇] → [`get_neighbor_chunks`] 补跨段证据 → [`check_evidence`]。**禁止**对库内每篇 `get_document_full_text`；**禁止**未检索就臆造跨文档关系。 |
| 已知 `doc_id`，仅要结构/导航（章节树、表图索引；**非**全文综合作答） | `get_document_summary` → [`get_document_outline`（`include_previews` 视需要）] → `query_knowledge_hub` 或 `search_by_metadata` |
| 问 Figure/图/架构示意、`has_image`、或 `section_title` 强绑定图 | `search_by_metadata`（`filters` 含 `has_image`/`section_title` 等）→ [`get_neighbor_chunks`] → [`check_evidence`] |
| 问 Table/对比表、`evidence_locator` 含 Table、或需窄 doc | `search_by_metadata`（`filters` 收窄 `doc_id`/`section_title`/`has_table`）→ [`get_neighbor_chunks`] → [`check_evidence`] |
| 检索命中元数据 **`has_table`/`has_image`** 或答案明显跨段 | 在同一子任务内：**先**对锚点 `chunk_id` **`get_neighbor_chunks`**（常用 `window:2`），再生成/校验；**勿**未扩窗就编造表/图细节 |
| 要验证某陈述是否被库支持 | `query_knowledge_hub` 或 `search_by_metadata` → [`get_neighbor_chunks`] → `check_evidence` |
| 开放域知识库问答（默认） | `query_knowledge_hub` → [`get_neighbor_chunks`] → [`check_evidence`] |
| **DEFAULT（上表无任何行匹配）** | 在 **`tools/list` 出现的工具名集合** 内，由 LLM **自排调用顺序**；**约束**：先检索（`query_knowledge_hub` 或 `search_by_metadata`）再扩窗/精读；表/图/跨段优先 `get_neighbor_chunks`；事实性输出尽量 `check_evidence`；禁止臆造未返回内容；`need_image`/`need_table` 须在答复中提示对照原文 |

## `question_type`（对齐 `demo10_clean_eval_multigold.jsonl`）

| `question_type` | 推荐链（与 hub 已返全文一致；评测行内或含 `read_chunk` 时可照跑评测） |
|-----------------|-------------------------------------------------------------------|
| `contribution` `method` `motivation` `result` `dataset` `evaluation` `license` `trend` | `query_knowledge_hub` → [`get_neighbor_chunks`] → [`check_evidence`]（**非**单篇/跨篇「通读综合」；若问整篇脉络见下行或主路由表） |
| `comparison` | **跨文档综合性**：见上表「跨多篇文档」行。已锁 Table/doc：`search_by_metadata` 优先；否则 `query_knowledge_hub` → [`get_neighbor_chunks`] → [`check_evidence`] |
| `figure_qa` | `search_by_metadata` → [`get_neighbor_chunks`] → [`check_evidence`] |
| `overview` `structure`（且明确**单篇**全文/整体结构） | 已知 `doc_id`：`get_document_summary` → [`get_document_outline`] → 若需正文细节再 `get_document_full_text`；**单篇综合**优先全文工具而非仅 top-k |
| （评测/任务标注为**单文档综合**） | 同「单篇文档综合性问题」行 |
| （评测/任务标注为**多文档/跨文档综合**） | 同「跨多篇文档综合性问题」行 |

评测数据：`data/demo10_clean_eval_multigold/demo10_clean_eval_multigold.jsonl`（字段含 `expected_tools`，跑金标准时以行为准）。

## Query 写法（极简）

去口语语气词；保留英文术语 + 中文关键词。`filters` 能收窄则写上。

**demo10 句式样例**：贡献类「X 主要解决…？」；方法类「X 如何构造…？」；对比「与 Y 相比 X…？」；图「Figure k 中…？」。

**综合性问题句式样例**：

- **单篇**：「请综合概括这篇论文的主要贡献与局限」→ 先锁 `doc_id`，再 `get_document_full_text`。
- **跨篇**：「对比 A 与 B 两篇在检索增强上的差异」→ 检索两篇 → 可选各 `get_document_summary`，**勿**默认两篇都拉全文除非篇幅允许。
- **跨篇/综述**：「ACL 2024 中 RAG 方向的整体趋势」→ `query_knowledge_hub` 多命中 → 归纳；仅对 1~2 篇代表作 `get_document_full_text` 补细节。
