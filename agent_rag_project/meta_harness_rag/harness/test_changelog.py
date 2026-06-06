"""agent_rag/test/TEST_CHANGELOG.md — Evaluator 改写测试文件时的变更记录。"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.gates import is_gate_task
from harness.types import HarnessTask

_DEFAULT_REL = "test/TEST_CHANGELOG.md"
_ENTRY_SEP = "\n\n---\n\n"
_TEST_FN_RE = re.compile(r"^\s*def\s+(test_\w+)\s*\(", re.MULTILINE)


def changelog_rel_path(harness_cfg: dict, evaluator_cfg: dict | None = None) -> str:
    ev = evaluator_cfg or {}
    return str(
        ev.get("test_changelog_path")
        or harness_cfg.get("test_changelog_path")
        or _DEFAULT_REL
    )


def changelog_abs_path(product_root: Path, harness_cfg: dict, evaluator_cfg: dict | None = None) -> Path:
    return product_root / changelog_rel_path(harness_cfg, evaluator_cfg)


def build_changelog_header() -> str:
    return """# 测试变更记录（TEST_CHANGELOG）

> **Harness Evaluator 自动维护**：当 Evaluator 通过 `write_tests` 新建/补全/修正测试文件时追加一条记录。
> 与 [`TEST_INDEX.md`](TEST_INDEX.md)（测什么）、[`TEST_PROGRESS.md`](TEST_PROGRESS.md)（跑得怎样）互补；本文件记录**测码本身改了什么**。
>
> 配置：`meta_harness_rag/config/harness.yaml` → `evaluator.test_changelog_update` / `test_changelog_path`。

## 记录说明

| 字段 | 含义 |
|------|------|
| 操作 | `create` 新建 / `supplement` 补全 / `fix` 修正 |
| 子任务 | Harness `task_id`（`gate.*` 为门禁） |
| 测试文件 | 相对 `agent_rag/` 的路径 |
| 变更摘要 | 行数、`test_*` 函数增减 |
| diff | 改写前后 unified diff（过长会截断） |

## 变更条目

（以下由 Evaluator 追加；最新在文末。）

"""


def read_changelog(path: Path) -> str:
    if not path.is_file():
        return build_changelog_header()
    text = path.read_text(encoding="utf-8", errors="replace")
    if "## 变更条目" not in text:
        return build_changelog_header() + _ENTRY_SEP
    return text


def _action_label(action: str) -> str:
    return {
        "create": "新建",
        "supplement": "补全",
        "fix": "修正",
    }.get(action, action or "更新")


def _summarize_test_functions(old_code: str, new_code: str) -> str:
    old_fns = set(_TEST_FN_RE.findall(old_code))
    new_fns = set(_TEST_FN_RE.findall(new_code))
    added = sorted(new_fns - old_fns)
    removed = sorted(old_fns - new_fns)
    parts = [f"共 {len(new_fns)} 个 `test_*`"]
    if added:
        parts.append(f"新增: {', '.join(added)}")
    if removed:
        parts.append(f"移除: {', '.join(removed)}")
    return "；".join(parts)


def _summarize_lines(old_code: str, new_code: str) -> str:
    old_lines = old_code.count("\n") + (1 if old_code and not old_code.endswith("\n") else 0)
    new_lines = new_code.count("\n") + (1 if new_code and not new_code.endswith("\n") else 0)
    if not old_code.strip():
        return f"行数: 0 → {new_lines}（新建）"
    delta = new_lines - old_lines
    sign = f"+{delta}" if delta >= 0 else str(delta)
    return f"行数: {old_lines} → {new_lines}（{sign}）"


def _build_diff_block(
    rel_path: str,
    old_code: str,
    new_code: str,
    *,
    max_chars: int | None,
) -> str:
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)
    if not old_lines and not new_lines:
        return "（无 diff）\n"
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )
    if not diff_lines:
        return "（内容与改写前相同，无 diff 行）\n"
    body = "\n".join(diff_lines)
    if max_chars is not None and len(body) > max_chars:
        body = body[: max_chars - 40] + "\n…[diff 截断]\n"
    return f"```diff\n{body}\n```\n"


def format_change_entry(
    task: HarnessTask,
    *,
    test_rel: str,
    action: str,
    reason: str,
    old_code: str,
    new_code: str,
    diff_max_chars: int | None = 8000,
) -> str:
    """生成单条 markdown 变更记录（不含首尾 ---）。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    tid = str(task.get("id", "")).strip() or "（无 id）"
    cls = str(task.get("target_class") or task.get("module") or "")
    sym = str(task.get("symbol", ""))
    target = f"{cls}.{sym}" if cls and sym else cls or sym or "—"
    gate = "是" if is_gate_task(task) else "否"
    label = _action_label(action)
    reason_trim = (reason or "").strip().replace("\n", " ")[:500]

    lines = [
        f"### {now} — `{tid}`",
        "",
        "| 字段 | 值 |",
        "|------|-----|",
        f"| 操作 | {label} (`{action}`) |",
        f"| 子任务 | `{tid}` |",
        f"| 测试文件 | `{test_rel}` |",
        f"| 目标 | {target} |",
        f"| 门禁任务 | {gate} |",
        f"| 原因 | {reason_trim or '—'} |",
        "",
        "#### 变更摘要",
        "",
        f"- {_summarize_lines(old_code, new_code)}",
        f"- {_summarize_test_functions(old_code, new_code)}",
        "",
        "#### diff",
        "",
        _build_diff_block(test_rel, old_code, new_code, max_chars=diff_max_chars).rstrip(),
    ]
    return "\n".join(lines)


def append_test_change(
    path: Path,
    task: HarnessTask,
    *,
    test_rel: str,
    action: str,
    reason: str,
    old_code: str,
    new_code: str,
    diff_max_chars: int | None = 8000,
) -> str:
    """
    向 TEST_CHANGELOG.md 追加一条记录。返回简短状态说明。
    若新旧内容完全相同则跳过写入。
    """
    old_code = old_code or ""
    new_code = new_code or ""
    if old_code.rstrip() == new_code.rstrip():
        return "TEST_CHANGELOG 未追加（内容无变化）"

    path.parent.mkdir(parents=True, exist_ok=True)
    base = read_changelog(path)
    if not base.endswith("\n"):
        base += "\n"
    entry = format_change_entry(
        task,
        test_rel=test_rel.replace("\\", "/"),
        action=action,
        reason=reason,
        old_code=old_code,
        new_code=new_code,
        diff_max_chars=diff_max_chars,
    )
    path.write_text(base.rstrip() + _ENTRY_SEP + entry + "\n", encoding="utf-8")
    return f"已写入 TEST_CHANGELOG（{test_rel}）"


def changelog_diff_max_chars(evaluator_cfg: dict | None) -> int | None:
    """evaluator.test_changelog_diff_max_chars：0 或省略=不截断 diff。"""
    ev = evaluator_cfg or {}
    if "test_changelog_diff_max_chars" not in ev:
        return 8000
    try:
        v = int(ev["test_changelog_diff_max_chars"])
    except (TypeError, ValueError):
        return 8000
    if v <= 0:
        return None
    return v
