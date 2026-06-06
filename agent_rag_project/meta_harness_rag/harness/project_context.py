"""为 Generator 组装只读工程上下文：tech_doc + 多棵只读代码树（agent_rag/、MCP Server 等）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_DEFAULT_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
}


def read_text(path: Path, max_chars: int | None = None) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 20] + "\n…[truncated]\n"
    return text


def list_python_files(
    root: Path,
    *,
    skip_dirs: Iterable[str] | None = None,
    max_files: int = 200,
) -> list[Path]:
    if not root.is_dir():
        return []
    skip = set(skip_dirs or _DEFAULT_SKIP_DIRS)
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            out.append(Path(dirpath) / name)
            if len(out) >= max_files:
                return sorted(out)
    return sorted(out)


def _display_rel(fp: Path, package_root: Path, scan_root: Path) -> str:
    if fp.is_relative_to(package_root):
        return fp.relative_to(package_root).as_posix()
    if fp.is_relative_to(scan_root):
        return fp.relative_to(scan_root).as_posix()
    return fp.as_posix()


def resolve_read_only_roots(package_root: Path, harness_cfg: dict) -> list[dict]:
    """
    解析 Harness 只读代码根目录。
    默认：agent_rag/agent_rag/ + MCP Server src/mcp_server（与 rag_agent.mcp.stdio 子项目对齐）。
    """
    configured = harness_cfg.get("read_only_code_roots")
    if configured:
        roots: list[dict] = []
        for item in configured:
            if isinstance(item, str):
                roots.append({"label": item, "path": item, "max_chars": None})
            elif isinstance(item, dict):
                roots.append(item)
        return roots

    impl = harness_cfg.get("implementation_root", "../agent_rag/agent_rag")
    gen = harness_cfg.get("generator") or {}
    mcp_rel = (
        harness_cfg.get("mcp_server_code_path")
        or "../mcp_rag/src/mcp_server"
    )
    return [
        {
            "label": f"RAG 产品实现 ({impl}/)",
            "path": impl,
            "max_chars": gen.get("rag_code_max_chars"),
            "max_files": gen.get("rag_max_files", 200),
        },
        {
            "label": "MCP Server 只读 (src/mcp_server，对接 tools/call)",
            "path": mcp_rel,
            "max_chars": gen.get("mcp_server_code_max_chars", 150_000),
            "max_files": gen.get("mcp_server_max_files", 50),
        },
    ]


def _snapshot_tree(
    *,
    label: str,
    scan_root: Path,
    package_root: Path,
    per_file_max_chars: int,
    tree_max_chars: int | None,
    max_files: int,
    extra_files: list[Path] | None = None,
) -> str:
    lines = [f"\n=== {label} ===", f"根目录: {scan_root.resolve()}"]
    if "harness" in scan_root.parts and scan_root.name == "harness":
        lines.append("（跳过：不扫描 harness 自身）")
        return "\n".join(lines)

    paths = list_python_files(scan_root, max_files=max_files)
    if extra_files:
        for p in extra_files:
            if p.is_file() and p.suffix == ".py" and p not in paths:
                paths.append(p)
    paths = sorted(set(paths))

    if not paths:
        lines.append("（目录不存在或尚无 .py 文件）")
        return "\n".join(lines)

    parts: list[str] = []
    used = 0
    for fp in paths:
        rel = _display_rel(fp, package_root, scan_root)
        body = read_text(fp, per_file_max_chars)
        if not body.strip():
            continue
        chunk = f"\n--- file: {rel} ---\n{body}"
        cap = tree_max_chars
        if cap is not None and used + len(chunk) > cap:
            parts.append("\n…[本树代码快照截断]…")
            break
        parts.append(chunk)
        used += len(chunk)

    lines.append("".join(parts) if parts else "（无有效文件内容）")
    return "\n".join(lines)


def build_project_context(
    *,
    package_root: Path,
    tech_doc_path: Path,
    read_only_roots: list[dict] | None = None,
    harness_cfg: dict | None = None,
    code_root: Path | None = None,
    extra_paths: list[Path] | None = None,
    tech_doc_max_chars: int = 120_000,
    per_file_max_chars: int = 15_000,
    total_code_max_chars: int = 200_000,
) -> str:
    """
    组装 Generator prompt 用只读上下文。

    - **写入**仍仅限 ``implementation_root``（默认 ``rag/``）
    - **只读快照**可含多目录，例如 ``rag/`` + 父仓 ``src/mcp_server``
    - **永不**扫描 ``harness/``
    """
    harness_cfg = harness_cfg or {}
    gen_cfg = harness_cfg.get("generator") or {}

    if read_only_roots is None:
        read_only_roots = resolve_read_only_roots(package_root, harness_cfg)
    elif code_root is not None:
        # 向后兼容：仅传 code_root 时当作唯一 rag 树
        read_only_roots = [
            {
                "label": "RAG 产品实现",
                "path": str(code_root.relative_to(package_root))
                if code_root.is_relative_to(package_root)
                else str(code_root),
                "max_chars": None,
            }
        ]

    sections: list[str] = []
    sections.append("=== tech_doc（全文，只读） ===")
    sections.append(read_text(tech_doc_path, tech_doc_max_chars))

    sections.append(
        "\n=== 只读代码快照（供实现/对接 MCP 参考；勿改 harness/；实现产物只写入 agent_rag/agent_rag/） ==="
    )

    code_blob_parts: list[str] = []
    total_used = 0

    for entry in read_only_roots:
        label = entry.get("label") or entry.get("path", "?")
        raw_path = entry.get("path", "")
        scan_root = (package_root / raw_path).resolve()
        if "harness" in {p.lower() for p in scan_root.parts} and scan_root.name.lower() == "harness":
            continue

        tree_max = entry.get("max_chars")
        max_files = int(entry.get("max_files", 200))
        tree_text = _snapshot_tree(
            label=label,
            scan_root=scan_root,
            package_root=package_root,
            per_file_max_chars=per_file_max_chars,
            tree_max_chars=tree_max,
            max_files=max_files,
            extra_files=extra_paths if entry == read_only_roots[0] else None,
        )
        if total_code_max_chars and total_used + len(tree_text) > total_code_max_chars:
            code_blob_parts.append("\n…[总代码快照已达上限，后续目录省略]…")
            break
        code_blob_parts.append(tree_text)
        total_used += len(tree_text)

    sections.append("\n".join(code_blob_parts))
    return "\n".join(sections)
