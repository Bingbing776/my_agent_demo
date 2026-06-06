"""agent_rag/test/TEST_PROGRESS.md — 由 Harness Evaluator LLM 维护的测试进度表。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from harness.gates import is_gate_task
from harness.types import HarnessEvalResult, HarnessTask

_DEFAULT_REL = "test/TEST_PROGRESS.md"


def _retry_limits_from_config(
    harness_cfg: dict | None,
    evaluator_cfg: dict | None = None,
) -> tuple[int, int]:
    """从 Harness 配置读取与「失败/重试耗尽」相关的上限。"""
    harness_cfg = harness_cfg or {}
    ev = evaluator_cfg or harness_cfg.get("evaluator") or {}
    gen = harness_cfg.get("generator") or {}
    max_inner = int(gen.get("max_inner_steps", 8))
    streak = int(ev.get("quick_rule_error_streak", 3))
    return max_inner, streak


def fail_legend_line(
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> str:
    max_inner, streak = _retry_limits_from_config(harness_cfg, evaluator_cfg)
    return (
        "| ❌ | Fail — exhausted configured retry limits "
        f"(`generator.max_inner_steps`={max_inner}, "
        f"`evaluator.quick_rule_error_streak`={streak}; "
        "see `meta_harness_rag/config/harness.yaml` and product `settings.yaml`) |"
    )


def build_progress_header(
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> str:
    """生成含当前配置值的图例（❌ 行随 harness.yaml 更新）。"""
    max_inner, streak = _retry_limits_from_config(harness_cfg, evaluator_cfg)
    return f"""# 测试进度（TEST_PROGRESS）

> **Harness Evaluator 维护**：每轮子任务评估后更新对应行；与 [`TEST_INDEX.md`](TEST_INDEX.md) 互补。
> **行来源**：`TEST_INDEX` 登记项 + 扫描 `test/**/test_*.py`（`evaluator.test_progress_discover_all`）。
> **版式**：进度表按类别分组（`Unit · 组件` / `Contracts` / `Integration` / `E2E` / `Nonfunctional`），类与类之间空一行。
> 图例中 ❌ 的上限：`max_inner_steps={max_inner}`，`quick_rule_error_streak={streak}`。

## 状态图例

| Icon | Meaning |
|------|---------|
| ✅ | Pass — all assertions verified against actual output |
{fail_legend_line(harness_cfg, evaluator_cfg)}
| ⏭️ | Skip — missing third-party API key (K-series only) |
| 🔧 | Fix applied — needs re-test |
| ⬜ | Pending — not yet tested |

## 进度表

| Progress | test_file | test_function | target_class | target_symbol | Last run | Notes |
|----------|-----------|---------------|--------------|---------------|----------|-------|
"""

_ROW_RE = re.compile(
    r"^\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]*)\|\s*([^|]*)\|\s*$"
)

_VALID_ICONS = frozenset({"✅", "❌", "⏭️", "🔧", "⬜"})

_UNIT_CLASS_ORDER = [
    "ContextManager",
    "MemoryManager",
    "McpClient",
    "Executor",
    "PlannerAgent",
    "Evaluator",
    "Generator",
    "RagOrchestrator",
    "Unknown",
]

_CLASS_PREFIX: dict[str, str] = {
    "memory": "MemoryManager",
    "context": "ContextManager",
    "mcp_client": "McpClient",
    "executor": "Executor",
    "planner": "PlannerAgent",
    "evaluator": "Evaluator",
    "generator": "Generator",
    "orchestrator": "RagOrchestrator",
}

_PROGRESS_ALIASES: dict[str, str] = {
    "pass": "✅",
    "passed": "✅",
    "ok": "✅",
    "success": "✅",
    "fail": "❌",
    "failed": "❌",
    "failure": "❌",
    "error": "❌",
    "skip": "⏭️",
    "skipped": "⏭️",
    "fix": "🔧",
    "fixed": "🔧",
    "retest": "🔧",
    "pending": "⬜",
    "todo": "⬜",
    "unknown": "⬜",
}


def progress_rel_path(harness_cfg: dict, evaluator_cfg: dict | None = None) -> str:
    ev = evaluator_cfg or {}
    return str(
        ev.get("test_progress_path")
        or harness_cfg.get("test_progress_path")
        or _DEFAULT_REL
    )


def progress_abs_path(product_root: Path, harness_cfg: dict, evaluator_cfg: dict | None = None) -> Path:
    return product_root / progress_rel_path(harness_cfg, evaluator_cfg)


def normalize_progress_icon(
    raw: Any,
    *,
    passed: bool | None = None,
    status: str | None = None,
    tests_just_updated: bool = False,
) -> str:
    """将 LLM / 规则输出规范为五种图标之一。"""
    if raw is not None:
        s = str(raw).strip()
        if s in _VALID_ICONS:
            return s
        key = s.lower().strip(" '\"")
        if key in _PROGRESS_ALIASES:
            return _PROGRESS_ALIASES[key]
        if key in _VALID_ICONS:
            return key

    if status == "hard_fail":
        return "❌"
    if tests_just_updated and not passed:
        return "🔧"
    if passed is True:
        return "✅"
    if passed is False:
        return "❌"
    return "⬜"


def is_retry_exhausted(
    eval_result: HarnessEvalResult,
    *,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
    tool_trace_summary: str = "",
) -> bool:
    """是否已达配置的重试/内层步数上限（与图例 ❌ 对齐）。"""
    max_inner, streak = _retry_limits_from_config(harness_cfg, evaluator_cfg)
    status = str(eval_result.get("status", "ok"))
    issues = str(eval_result.get("issues", ""))
    if status == "hard_fail":
        return True
    if "max_inner_steps" in issues:
        return True
    if f"连续 {streak}" in issues and "[error]" in issues:
        return True
    if tool_trace_summary and tool_trace_summary.count("[error]") >= streak:
        return True
    return False


def progress_note_for_exhaustion(
    eval_result: HarnessEvalResult,
    *,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> str:
    """配置上限用尽时的标准 Notes 文案。"""
    max_inner, streak = _retry_limits_from_config(harness_cfg, evaluator_cfg)
    issues = str(eval_result.get("issues", ""))
    if "max_inner_steps" in issues:
        return f"已达 generator.max_inner_steps={max_inner}"
    if str(eval_result.get("status")) == "hard_fail" or (
        f"连续 {streak}" in issues and "[error]" in issues
    ):
        return f"已达 evaluator.quick_rule_error_streak={streak}"
    return ""


def infer_progress_from_eval(
    eval_result: HarnessEvalResult,
    *,
    tests_just_updated: bool = False,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
    tool_trace_summary: str = "",
) -> str:
    if is_retry_exhausted(
        eval_result,
        harness_cfg=harness_cfg,
        evaluator_cfg=evaluator_cfg,
        tool_trace_summary=tool_trace_summary,
    ):
        return "❌"
    status = str(eval_result.get("status", "ok"))
    passed = bool(eval_result.get("passed", False))
    if tests_just_updated and not passed:
        return "🔧"
    if passed and not eval_result.get("require_more_tools", False):
        return "✅"
    if passed is False:
        return "❌"
    return "⬜"


def read_progress(
    path: Path,
    *,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> str:
    if not path.is_file():
        return build_progress_header(harness_cfg, evaluator_cfg) + "\n"
    return path.read_text(encoding="utf-8", errors="replace")


def row_category(row: dict[str, str]) -> str:
    """进度表分组标题（写入分隔行）。"""
    tf = str(row.get("test_file", "")).replace("\\", "/")
    parts = tf.split("/")
    if len(parts) >= 2 and parts[0] == "test":
        layer = parts[1].lower()
        if layer == "unit":
            cls = str(row.get("target_class") or "").strip() or "Unknown"
            return f"Unit · {cls}"
        names = {
            "contracts": "Contracts",
            "integration": "Integration",
            "e2e": "E2E",
            "nonfunctional": "Nonfunctional",
        }
        return names.get(layer, layer.capitalize())
    return "Other"


def category_sort_key(category: str) -> tuple[int, int, str]:
    if category.startswith("Unit · "):
        cls = category[7:]
        try:
            order = _UNIT_CLASS_ORDER.index(cls)
        except ValueError:
            order = 99
        return (0, order, category)
    layer_order = {
        "Contracts": (1, 0),
        "Integration": (2, 0),
        "E2E": (3, 0),
        "Nonfunctional": (4, 0),
        "Other": (5, 0),
    }
    for name, (a, b) in layer_order.items():
        if category == name:
            return (a, b, category)
    return (6, 0, category)


def _is_section_separator_row(progress: str, test_function: str) -> bool:
    p = progress.strip()
    fn = test_function.strip()
    if p not in ("·", "—", "–", ""):
        return False
    return fn.startswith("**") and fn.endswith("**")


def parse_progress_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        if "| Progress |" in line and "test_file |" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.strip():
            continue
        if re.match(r"^\|\s*[-:]+\s*\|", line):
            continue
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        progress, tf, fn, cls, sym, last_run, notes = [g.strip() for g in m.groups()]
        if progress.lower() == "progress" or tf.lower() == "test_file":
            continue
        if _is_section_separator_row(progress, fn):
            continue
        rows.append(
            {
                "progress": progress,
                "test_file": tf.replace("\\", "/"),
                "test_function": fn,
                "target_class": cls,
                "target_symbol": sym,
                "last_run": last_run,
                "notes": notes,
            }
        )
    return rows


def _row_key(test_file: str, test_function: str) -> tuple[str, str]:
    return (test_file.replace("\\", "/"), test_function.strip())


def format_progress_document(
    rows: list[dict[str, str]],
    *,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> str:
    lines = [build_progress_header(harness_cfg, evaluator_cfg).rstrip()]
    by_cat: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_cat.setdefault(row_category(r), []).append(r)

    first_group = True
    for cat in sorted(by_cat.keys(), key=category_sort_key):
        if not first_group:
            lines.append("")
        first_group = False
        lines.append(f"| · | **{cat}** | · | · | · | · | · |")
        for r in sorted(
            by_cat[cat],
            key=lambda x: (x.get("test_file", ""), x.get("test_function", "")),
        ):
            lines.append(
                f"| {r.get('progress', '⬜')} | {r.get('test_file', '')} | {r.get('test_function', '')} | "
                f"{r.get('target_class', '')} | {r.get('target_symbol', '')} | "
                f"{r.get('last_run', '')} | {r.get('notes', '')} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_progress(
    path: Path,
    rows: list[dict[str, str]],
    *,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        format_progress_document(rows, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg),
        encoding="utf-8",
    )


def bootstrap_rows_from_index(index_entries: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for e in index_entries:
        if e.get("status") == "deleted":
            continue
        tf = e.get("test_file", "")
        fn = e.get("test_function", "")
        key = _row_key(tf, fn)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "progress": "⬜",
                "test_file": tf,
                "test_function": fn,
                "target_class": e.get("target_class", ""),
                "target_symbol": e.get("target_symbol", ""),
                "last_run": "",
                "notes": "",
            }
        )
    return rows


def merge_bootstrap(existing: list[dict[str, str]], index_entries: list[dict[str, str]]) -> list[dict[str, str]]:
    by_key = {_row_key(r["test_file"], r["test_function"]): r for r in existing}
    for e in bootstrap_rows_from_index(index_entries):
        key = _row_key(e["test_file"], e["test_function"])
        if key not in by_key:
            by_key[key] = e
    return list(by_key.values())


def _discover_enabled(
    evaluator_cfg: dict | None,
    harness_cfg: dict | None,
) -> bool:
    ev = evaluator_cfg or (harness_cfg or {}).get("evaluator") or {}
    return bool(ev.get("test_progress_discover_all", True))


def _infer_unit_class_symbol(stem: str, fn: str) -> tuple[str, str]:
    """从 test/unit/test_<stem>.py 推断 target_class / target_symbol。"""
    body = stem.replace("test_", "", 1) if stem.startswith("test_") else stem
    cls = "Unknown"
    sym = body
    for prefix, cname in _CLASS_PREFIX.items():
        if body.startswith(prefix + "_") or body == prefix:
            cls = cname
            sym = body[len(prefix) + 1 :] if body.startswith(prefix + "_") else body
            if sym in ("manager_init", "init"):
                sym = "__init__"
            break
    if sym == fn.replace("test_", "", 1) and sym != "__init__":
        pass
    return cls, sym


def discover_rows_from_test_tree(product_root: Path) -> list[dict[str, str]]:
    """扫描 test/**/test_*.py，登记全部 pytest 函数（含 contracts/e2e 等）。"""
    from harness.test_index import list_test_functions

    rows: list[dict[str, str]] = []
    test_root = product_root / "test"
    if not test_root.is_dir():
        return rows

    skip_parts = ("__pycache__", "helpers", "_generate_test_files.py")
    for py in sorted(test_root.rglob("test_*.py")):
        rel = py.relative_to(product_root).as_posix()
        if any(s in rel for s in skip_parts):
            continue
        code = py.read_text(encoding="utf-8", errors="replace")
        fns = list_test_functions(code)
        if not fns:
            continue
        parts = rel.split("/")
        layer = parts[1].lower() if len(parts) >= 2 and parts[0] == "test" else "other"
        stem = py.stem
        layer_cls = {
            "contracts": "Contracts",
            "integration": "Integration",
            "e2e": "E2E",
            "nonfunctional": "Nonfunctional",
        }.get(layer, layer.capitalize())
        for fn in fns:
            if layer == "unit":
                cls, sym = _infer_unit_class_symbol(stem, fn)
            else:
                cls, sym = layer_cls, fn
            rows.append(
                {
                    "progress": "⬜",
                    "test_file": rel,
                    "test_function": fn,
                    "target_class": cls,
                    "target_symbol": sym,
                    "last_run": "",
                    "notes": "",
                }
            )
    return rows


def merge_all_progress_sources(
    existing: list[dict[str, str]],
    index_entries: list[dict[str, str]],
    *,
    product_root: Path | None = None,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
) -> list[dict[str, str]]:
    """合并已有行、TEST_INDEX、可选的全目录扫描。"""
    by_key = {_row_key(r["test_file"], r["test_function"]): dict(r) for r in existing}
    for e in bootstrap_rows_from_index(index_entries):
        key = _row_key(e["test_file"], e["test_function"])
        if key not in by_key:
            by_key[key] = {
                "progress": "⬜",
                "test_file": e["test_file"],
                "test_function": e["test_function"],
                "target_class": e.get("target_class", ""),
                "target_symbol": e.get("target_symbol", ""),
                "last_run": "",
                "notes": "",
            }
        else:
            for field in ("target_class", "target_symbol"):
                if e.get(field) and not by_key[key].get(field):
                    by_key[key][field] = e[field]
    if product_root and _discover_enabled(evaluator_cfg, harness_cfg):
        for d in discover_rows_from_test_tree(product_root):
            key = _row_key(d["test_file"], d["test_function"])
            if key not in by_key:
                by_key[key] = d
    return list(by_key.values())


def resolve_row_for_task(
    rows: list[dict[str, str]],
    task: HarnessTask,
    index_entries: list[dict[str, str]],
) -> dict[str, str] | None:
    """为当前子任务找到应对应更新的进度行（优先 test_file + 索引中的 test_function）。"""
    tf = str(task.get("test_file", "")).replace("\\", "/")
    sym = str(task.get("symbol", ""))
    cls = str(task.get("target_class") or task.get("module") or "")

    if tf:
        candidates = [r for r in rows if r.get("test_file") == tf]
        if len(candidates) == 1:
            return candidates[0]
        for r in candidates:
            if r.get("target_symbol") == sym:
                return r
        if candidates:
            return candidates[0]

        related = [
            e
            for e in index_entries
            if e.get("test_file", "").replace("\\", "/") == tf
            and e.get("status") != "deleted"
        ]
        if related:
            e = related[0]
            return {
                "progress": "⬜",
                "test_file": tf,
                "test_function": e.get("test_function", f"test_{sym}"),
                "target_class": cls or e.get("target_class", ""),
                "target_symbol": sym or e.get("target_symbol", ""),
                "last_run": "",
                "notes": "",
            }

    for e in index_entries:
        if e.get("status") == "deleted":
            continue
        if (
            str(e.get("target_class", "")) == cls
            and str(e.get("target_symbol", "")) == sym
        ):
            key = _row_key(e["test_file"], e["test_function"])
            for r in rows:
                if _row_key(r["test_file"], r["test_function"]) == key:
                    return r
            return {
                "progress": "⬜",
                "test_file": e["test_file"],
                "test_function": e["test_function"],
                "target_class": cls,
                "target_symbol": sym,
                "last_run": "",
                "notes": "",
            }
    return None


def sync_progress_from_index(
    path: Path,
    index_entries: list[dict[str, str]],
    *,
    product_root: Path | None = None,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
    mark_test_file: str | None = None,
    mark_icon: str = "🔧",
    mark_note: str = "",
) -> str:
    """
    将 TEST_INDEX（及可选 test/ 全扫描）合并进 TEST_PROGRESS（缺的行补 ⬜）。
    若指定 mark_test_file，则将该文件在表中的所有行标为 mark_icon（Evaluator 刚改测试时用）。
    """
    text = read_progress(path, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
    rows = merge_all_progress_sources(
        parse_progress_rows(text),
        index_entries,
        product_root=product_root,
        harness_cfg=harness_cfg,
        evaluator_cfg=evaluator_cfg,
    )
    rel_mark = (mark_test_file or "").replace("\\", "/")
    today = date.today().isoformat()
    marked = 0
    if rel_mark:
        icon = normalize_progress_icon(mark_icon)
        note = mark_note[:500]
        for r in rows:
            if r.get("test_file", "").replace("\\", "/") != rel_mark:
                continue
            r["progress"] = icon
            r["last_run"] = today
            if note:
                r["notes"] = note
            marked += 1
    write_progress(path, rows, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
    parts = [f"TEST_PROGRESS 已同步，共 {len(rows)} 行"]
    if rel_mark and marked:
        parts.append(f"已标记 {rel_mark} 下 {marked} 项为 {icon}")
    return "; ".join(parts)


def ensure_progress_rows_for_test_code(
    path: Path,
    test_file: str,
    test_code: str,
    task: HarnessTask,
    *,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
    default_icon: str = "🔧",
    note: str = "",
) -> str:
    """根据测试源码中的 def test_* 补进度行（索引尚未更新时的兜底）。"""
    from harness.test_index import list_test_functions

    rel = test_file.replace("\\", "/")
    fns = list_test_functions(test_code) or [f"test_{task.get('symbol', 'unknown')}"]
    cls = str(task.get("target_class") or task.get("module") or "")
    sym = str(task.get("symbol", ""))
    text = read_progress(path, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
    by_key = {_row_key(r["test_file"], r["test_function"]): r for r in parse_progress_rows(text)}
    icon = normalize_progress_icon(default_icon)
    today = date.today().isoformat()
    added = 0
    for fn in fns:
        key = _row_key(rel, fn)
        if key in by_key:
            row = by_key[key]
            row["progress"] = icon
            row["last_run"] = today
            if note:
                row["notes"] = note[:500]
            continue
        by_key[key] = {
            "progress": icon,
            "test_file": rel,
            "test_function": fn,
            "target_class": cls,
            "target_symbol": sym,
            "last_run": today,
            "notes": note[:500],
        }
        added += 1
    write_progress(path, list(by_key.values()), harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
    return f"TEST_PROGRESS 已从源码补登记 {rel}（新增 {added} 个 test_* 行）"


def _gate_scope_prefix(task: HarnessTask) -> str:
    rel = str(task.get("test_file", "")).replace("\\", "/").strip()
    if not rel:
        return ""
    if str(task.get("pytest_scope", "")) in ("directory", "marker"):
        return rel.rstrip("/") + "/"
    return rel


def update_progress_for_gate(
    rows: list[dict[str, str]],
    task: HarnessTask,
    *,
    icon: str,
    note: str = "",
) -> tuple[list[dict[str, str]], int]:
    """门禁任务：按 test_file 前缀批量更新 TEST_PROGRESS 行。"""
    prefix = _gate_scope_prefix(task)
    if not prefix:
        return rows, 0
    today = date.today().isoformat()
    n = 0
    for r in rows:
        tf = str(r.get("test_file", "")).replace("\\", "/")
        if tf.startswith(prefix) or tf == prefix.rstrip("/"):
            r["progress"] = normalize_progress_icon(icon)
            r["last_run"] = today
            if note:
                r["notes"] = note[:500]
            n += 1
    return rows, n


def upsert_task_progress(
    path: Path,
    task: HarnessTask,
    *,
    icon: str,
    note: str = "",
    index_entries: list[dict[str, str]] | None = None,
    harness_cfg: dict | None = None,
    evaluator_cfg: dict | None = None,
    product_root: Path | None = None,
) -> str:
    """更新或插入一行；返回简短说明。"""
    icon = normalize_progress_icon(icon)
    text = read_progress(path, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
    rows = parse_progress_rows(text)
    if index_entries is not None:
        rows = merge_all_progress_sources(
            rows,
            index_entries,
            product_root=product_root,
            harness_cfg=harness_cfg,
            evaluator_cfg=evaluator_cfg,
        )

    if is_gate_task(task):
        rows, n = update_progress_for_gate(rows, task, icon=icon, note=note)
        # 同步更新 INDEX 中该 gate 的汇总行
        row = resolve_row_for_task(rows, task, index_entries or [])
        if row is not None:
            row["progress"] = icon
            row["last_run"] = date.today().isoformat()
            if note:
                row["notes"] = note[:500]
        write_progress(path, rows, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
        return f"门禁 {task.get('id')}: 已更新 TEST_PROGRESS 下 {n} 行 → {icon}"

    row = resolve_row_for_task(rows, task, index_entries or [])
    if row is None:
        tf = str(task.get("test_file") or "（未登记）")
        fn = f"test_{task.get('symbol', 'unknown')}"
        row = {
            "progress": icon,
            "test_file": tf,
            "test_function": fn,
            "target_class": str(task.get("target_class") or task.get("module") or ""),
            "target_symbol": str(task.get("symbol", "")),
            "last_run": date.today().isoformat(),
            "notes": note[:500],
        }
        rows.append(row)
    else:
        row["progress"] = icon
        row["last_run"] = date.today().isoformat()
        if note:
            row["notes"] = note[:500]
        key = _row_key(row["test_file"], row["test_function"])
        rows = [r if _row_key(r["test_file"], r["test_function"]) != key else row for r in rows]

    write_progress(path, rows, harness_cfg=harness_cfg, evaluator_cfg=evaluator_cfg)
    return f"已更新 TEST_PROGRESS: {row.get('test_file')}::{row.get('test_function')} → {icon}"
