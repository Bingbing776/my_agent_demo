"""agent_rag/test/TEST_INDEX.md 的解析、查询与维护。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness.types import HarnessTask

_DEFAULT_REL = "test/TEST_INDEX.md"
_TABLE_ROW_RE = re.compile(
    r"^\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]*)\|\s*([^|]*)\|\s*$"
)
_TEST_FN_RE = re.compile(r"^\s*def\s+(test_\w+)\s*\(", re.MULTILINE)

_INDEX_DOC_HEADER = """# 测试索引（TEST_INDEX）

> **Harness / LLM 维护**：每个 `test_*` 函数对应「被测类 + 被测符号」；**`task_id` 以 `gate.` 开头**为门禁汇总行（见 `config/harness.yaml` → `milestones`）。
> Harness 向 LLM 提供**完整本表**作目录；LLM/程序**只打开表中与本任务对应的 test_file**，且只读表中列出的 `test_function` 片段，勿加载其它测试文件全文。
> 新增 / 删除 / 重命名测试文件或函数后，**必须同步更新本文件**。

## 索引表

| test_file | test_function | target_class | target_symbol | task_id | status |
|-----------|---------------|--------------|---------------|---------|--------|
"""


def index_rel_path(harness_cfg: dict, evaluator_cfg: dict | None = None) -> str:
    ev = evaluator_cfg or {}
    return str(
        ev.get("test_index_path")
        or harness_cfg.get("test_index_path")
        or _DEFAULT_REL
    )


def index_abs_path(product_root: Path, harness_cfg: dict, evaluator_cfg: dict | None = None) -> Path:
    return product_root / index_rel_path(harness_cfg, evaluator_cfg)


def read_index(path: Path) -> str:
    if not path.is_file():
        return _INDEX_DOC_HEADER + "\n"
    return path.read_text(encoding="utf-8", errors="replace")


def parse_entries(text: str) -> list[dict[str, str]]:
    """解析索引表行（跳过表头分隔行）。"""
    entries: list[dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        if line.strip().startswith("| test_file |"):
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r"^\|\s*[-:]+\s*\|", line):
            continue
        m = _TABLE_ROW_RE.match(line.strip())
        if not m:
            continue
        test_file, test_fn, cls, sym, task_id, status = [g.strip() for g in m.groups()]
        if test_file.lower() == "test_file":
            continue
        entries.append(
            {
                "test_file": test_file.replace("\\", "/"),
                "test_function": test_fn,
                "target_class": cls,
                "target_symbol": sym,
                "task_id": task_id,
                "status": status or "active",
            }
        )
    return entries


def format_entries(entries: list[dict[str, str]]) -> str:
    lines = [_INDEX_DOC_HEADER.rstrip()]
    for e in sorted(
        entries,
        key=lambda x: (x.get("test_file", ""), x.get("test_function", "")),
    ):
        if e.get("status", "active") == "deleted":
            continue
        lines.append(
            f"| {e.get('test_file', '')} | {e.get('test_function', '')} | "
            f"{e.get('target_class', '')} | {e.get('target_symbol', '')} | "
            f"{e.get('task_id', '')} | {e.get('status', 'active')} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_index(path: Path, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_entries(entries), encoding="utf-8")


def _norm(s: str) -> str:
    return s.strip().lower()


def lookup_test_file(
    entries: list[dict[str, str]],
    task: HarnessTask,
) -> str | None:
    """按 task_id 或 (target_class, target_symbol) 查主测试文件路径。"""
    tid = str(task.get("id", "")).strip()
    cls = str(task.get("target_class") or task.get("module") or "").strip()
    sym = str(task.get("symbol", "")).strip()

    by_tid = [e for e in entries if e.get("task_id") == tid and e.get("status") != "deleted"]
    if by_tid:
        return by_tid[0]["test_file"]

    matches = [
        e
        for e in entries
        if e.get("status") != "deleted"
        and _norm(e.get("target_class", "")) == _norm(cls)
        and _norm(e.get("target_symbol", "")) == _norm(sym)
    ]
    if matches:
        return matches[0]["test_file"]
    return None


def entries_for_task(entries: list[dict[str, str]], task: HarnessTask) -> list[dict[str, str]]:
    """索引中与当前子任务相关的行（task_id 或 class+symbol 匹配）。"""
    tid = str(task.get("id", "")).strip()
    cls = str(task.get("target_class") or task.get("module") or "").strip()
    sym = str(task.get("symbol", "")).strip()

    related: list[dict[str, str]] = []
    if not cls or not sym:
        return related

    for e in entries:
        if e.get("status") == "deleted":
            continue
        if tid and e.get("task_id") == tid:
            related.append(e)
            continue
        if (
            _norm(e.get("target_class", "")) == _norm(cls)
            and _norm(e.get("target_symbol", "")) == _norm(sym)
        ):
            related.append(e)
    return related


def excerpt_for_task(entries: list[dict[str, str]], task: HarnessTask) -> str:
    """当前任务在索引中的相关行（小表，用于日志）。"""
    related = entries_for_task(entries, task)
    if not related:
        return "（索引中暂无本任务行）"
    lines = ["| test_file | test_function | target_class | target_symbol | task_id |"]
    for e in related:
        lines.append(
            f"| {e['test_file']} | {e['test_function']} | {e['target_class']} | "
            f"{e['target_symbol']} | {e.get('task_id', '')} |"
        )
    return "\n".join(lines)


def _extract_file_header(code: str) -> str:
    """测试文件中第一个 test_ 之前的 import / pytestmark。"""
    lines: list[str] = []
    for line in code.splitlines():
        if re.match(r"^\s*def\s+test_", line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def extract_test_function_sources(code: str, function_names: list[str]) -> str:
    """只抽取索引表里列出的 test_* 函数体（不含同文件其它 test）。"""
    if not code.strip():
        return ""
    header = _extract_file_header(code)
    parts: list[str] = []
    if header:
        parts.append(header)
    seen: set[str] = set()
    for fn in function_names:
        if not fn or fn in seen:
            continue
        seen.add(fn)
        pat = rf"(def\s+{re.escape(fn)}\s*\([^)]*\):.*?)(?=\ndef\s+test_|\Z)"
        m = re.search(pat, code, re.DOTALL)
        if m:
            parts.append(m.group(1).strip())
        else:
            parts.append(f"# （索引项 {fn} 在文件中未找到）")
    return "\n\n".join(parts)


def load_indexed_test_code(
    product_root: Path,
    entries: list[dict[str, str]],
    task: HarnessTask,
    *,
    fallback_test_file: str | None = None,
) -> tuple[str, list[str]]:
    """
    按 TEST_INDEX 为本任务加载测试源码：只读相关 test_file，且只含表中 test_function。
    返回 (拼接后的 markdown 文本, 实际读取的 test_file 列表)。
    """
    related = entries_for_task(entries, task)
    files_read: list[str] = []

    if not related and fallback_test_file:
        path = product_root / fallback_test_file.replace("\\", "/")
        if path.is_file():
            code = path.read_text(encoding="utf-8", errors="replace")
            fns = list_test_functions(code)
            sliced = extract_test_function_sources(code, fns) if fns else code[:8000]
            files_read.append(fallback_test_file)
            return (
                f"### {fallback_test_file}（任务已带 test_file，索引无匹配行）\n```python\n{sliced}\n```",
                files_read,
            )
        return "（索引无匹配且回退测试文件不存在）", files_read

    if not related:
        return "（索引无本任务行，未加载任何测试源码）", files_read

    by_file: dict[str, list[str]] = {}
    for e in related:
        rel = e["test_file"]
        fn = e.get("test_function", "")
        if fn:
            by_file.setdefault(rel, [])
            if fn not in by_file[rel]:
                by_file[rel].append(fn)

    chunks: list[str] = []
    for rel in sorted(by_file.keys()):
        path = product_root / rel
        files_read.append(rel)
        if not path.is_file():
            chunks.append(f"### {rel}\n（文件不存在）\n")
            continue
        code = path.read_text(encoding="utf-8", errors="replace")
        sliced = extract_test_function_sources(code, by_file[rel])
        chunks.append(
            f"### {rel}（仅索引中的 test_function：{', '.join(by_file[rel])}）\n```python\n{sliced}\n```"
        )
    return "\n\n".join(chunks), files_read


def list_test_functions(test_code: str) -> list[str]:
    return _TEST_FN_RE.findall(test_code)


def upsert_file_rows(
    entries: list[dict[str, str]],
    *,
    test_file: str,
    target_class: str,
    target_symbol: str,
    task_id: str,
    test_functions: list[str],
) -> list[dict[str, str]]:
    """用新 test_functions 替换该 test_file 下属于同一 task/class/symbol 的行，保留其它行。"""
    test_file = test_file.replace("\\", "/")
    kept = [
        e
        for e in entries
        if e.get("test_file") != test_file
        or (
            e.get("task_id") != task_id
            and not (
                _norm(e.get("target_class", "")) == _norm(target_class)
                and _norm(e.get("target_symbol", "")) == _norm(target_symbol)
            )
        )
    ]
    fns = test_functions or ["test_placeholder"]
    for fn in fns:
        kept.append(
            {
                "test_file": test_file,
                "test_function": fn,
                "target_class": target_class,
                "target_symbol": target_symbol,
                "task_id": task_id,
                "status": "active",
            }
        )
    return kept


def mark_file_deleted(entries: list[dict[str, str]], test_file: str) -> list[dict[str, str]]:
    test_file = test_file.replace("\\", "/")
    out: list[dict[str, str]] = []
    for e in entries:
        if e.get("test_file") == test_file:
            e = dict(e)
            e["status"] = "deleted"
        out.append(e)
    return out


def bootstrap_entries_from_tests(product_root: Path, test_root: str = "test/unit") -> list[dict[str, str]]:
    """从现有 test_*.py 文件名启发式生成初始索引（仅首次无索引时）。"""
    entries: list[dict[str, str]] = []
    root = product_root / test_root
    if not root.is_dir():
        return entries

    class_prefix = {
        "memory": "MemoryManager",
        "context": "ContextManager",
        "mcp_client": "McpClient",
        "executor": "Executor",
        "planner": "PlannerAgent",
        "evaluator": "Evaluator",
        "generator": "Generator",
        "orchestrator": "RagOrchestrator",
    }

    for py in sorted(root.glob("test_*.py")):
        rel = f"test/unit/{py.name}".replace("\\", "/")
        code = py.read_text(encoding="utf-8", errors="replace")
        fns = list_test_functions(code) or [f"test_{py.stem.replace('test_', '')}"]
        stem = py.stem.replace("test_", "")
        cls = "Unknown"
        sym = stem
        for prefix, cname in class_prefix.items():
            if stem.startswith(prefix + "_") or stem == prefix:
                cls = cname
                sym = stem[len(prefix) + 1 :] if stem.startswith(prefix + "_") else stem
                if sym == "manager_init" or sym == "init":
                    sym = "__init__"
                sym = sym.replace("_", "_")  # keep
                break
        for fn in fns:
            entries.append(
                {
                    "test_file": rel,
                    "test_function": fn,
                    "target_class": cls,
                    "target_symbol": sym if sym != fn.replace("test_", "") else sym,
                    "task_id": "",
                    "status": "active",
                }
            )
    return entries
