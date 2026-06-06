# agent_rag 测试

针对 **`agent_rag/`** 产品包（tech_doc §1–§7），见 `test/helpers/imports.py`。

**测试索引**：[`TEST_INDEX.md`](TEST_INDEX.md) — Unit 符号级 + **`gate.*` 门禁**（`meta_harness_rag/config/harness.yaml` → `milestones`）；Harness Evaluator 按 INDEX 跑 pytest。

**测试进度**：[`TEST_PROGRESS.md`](TEST_PROGRESS.md) — 全部 91 项；门禁通过时按目录批量更新状态。

**测试变更**：[`TEST_CHANGELOG.md`](TEST_CHANGELOG.md) — Evaluator 改写测试文件时自动追加记录（含 diff）。

在 `agent_rag` 目录下：

```bash
python -m pytest test/contracts -q
python -m pytest test/unit -q
```

规格：`../meta_harness_rag/docs/tech_doc.md`。
