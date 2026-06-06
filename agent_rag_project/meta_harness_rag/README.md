# meta_harness_rag

**Harness**（写代码工具）：读 [`docs/tech_doc.md`](docs/tech_doc.md)，在同级目录 [`../agent_rag/`](../agent_rag/) 中**一次实现一个函数**。

RAG 产品运行时、测试与 `config/settings.yaml` 已迁至 **`agent_rag/`**，本目录仅保留 Harness。

| 目录 | 说明 |
|------|------|
| `harness/` | `HarnessPlanner`, `HarnessGenerator`, `HarnessEvaluator` |
| `core/` | `HarnessController` |
| `config/harness.yaml` | Harness 配置（`product_root` → `../agent_rag`） |
| `docs/` | `tech_doc.md`、架构说明 |

```bash
python main.py --dry-plan
python main.py --max-tasks 1
```

详见 [`docs/architecture.md`](docs/architecture.md)、[`docs/harness.md`](docs/harness.md)、[`docs/harness_architecture.md`](docs/harness_architecture.md)（Harness 整体架构与流程）。
