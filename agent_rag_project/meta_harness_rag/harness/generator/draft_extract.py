"""Extract Python snippets from Generator LLM drafts (permissive)."""
from __future__ import annotations

import ast
import re

from harness.generator.code_merge import extract_method_from_class_body, extract_method_source

_FENCE = re.compile(r"```(?:python|py)?\s*\n([\s\S]*?)```", re.IGNORECASE)
_CONTENT_TAG = re.compile(r"<content>\s*\n?([\s\S]*?)</content>", re.IGNORECASE)
_DEF_LINE = re.compile(r"^(\s*)(?:async\s+)?def (\w+)\b", re.MULTILINE)
_TOOL_MARKERS = (
    "<tool_use>",
    "<tool_call>",
    "<server_name>",
    "<file_read>",
    "<file_write>",
    "<file_search>",
    "<arguments>",
    "</tool_use>",
    "</tool_call>",
    "tool_name>",
    "tool_calls",
)


def list_def_symbols(code: str) -> list[str]:
    """Return def names in source order (deduplicated)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _DEF_LINE.finditer(code):
        name = m.group(2)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _join_fenced_blocks(draft: str) -> str:
    blocks = [m.group(1).strip() for m in _FENCE.finditer(draft) if m.group(1).strip()]
    if blocks:
        return "\n\n".join(blocks)
    return ""


def _extract_from_content_tag(draft: str) -> str:
    m = _CONTENT_TAG.search(draft)
    if not m:
        return ""
    code = m.group(1).strip()
    if "def " in code or "class " in code or "import " in code:
        return code
    return ""


def _extract_def_blocks(draft: str) -> str:
    """Pull every ``def`` block from mixed prose + code."""
    lines = draft.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not re.match(r"^\s*def \w+\b", line):
            i += 1
            continue
        base_indent = len(line) - len(line.lstrip())
        chunk = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                chunk.append(nxt)
                i += 1
                continue
            indent = len(nxt) - len(nxt.lstrip())
            if indent <= base_indent and re.match(r"^\s*(def |class |@)", nxt):
                break
            chunk.append(nxt)
            i += 1
        block = "\n".join(chunk).strip()
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def extract_code_from_draft(draft: str, *, relaxed: bool = True) -> str:
    """Extract Python from an LLM draft; prefer fenced blocks, then def blocks."""
    if not draft or not draft.strip():
        return ""

    for extractor in (_join_fenced_blocks, _extract_from_content_tag):
        code = extractor(draft)
        if code.strip():
            return code.strip()

    has_tool_markers = any(marker in draft for marker in _TOOL_MARKERS)
    if "def " in draft or "class " in draft:
        if has_tool_markers and not relaxed:
            return ""
        if "def " in draft:
            blocks = _extract_def_blocks(draft)
            if blocks.strip():
                return blocks.strip()
        return draft.strip()

    return ""


def prioritize_symbols(symbols: list[str], primary: str) -> list[str]:
    """Merge helpers first, primary symbol last."""
    if not symbols:
        return [primary] if primary else []
    helpers = [s for s in symbols if s != primary and s.startswith("_")]
    others = [s for s in symbols if s != primary and not s.startswith("_")]
    ordered = helpers + others
    if primary and primary in symbols:
        ordered.append(primary)
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in ordered:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


_TEST_SCRIPT_MARKERS = (
    "import pytest",
    "from unittest.mock import",
    "pytestmark",
    "@pytest.fixture",
    "@pytest.mark",
    "AsyncMock(",
    "MagicMock(",
    "MockSession",
    "asyncio.run(",
    "pytest.skip(",
)


def list_product_def_symbols(code: str) -> list[str]:
    """``def`` names in *code* excluding pytest-style ``test_*``."""
    return [name for name in list_def_symbols(code) if not name.startswith("test_")]


def draft_has_mergeable_product_defs(code: str) -> bool:
    """True when draft contains at least one non-test ``def`` to merge."""
    return bool(list_product_def_symbols(code))


def code_covers_symbol(code: str, symbol: str, *, target_class: str = "") -> bool:
    if not symbol:
        return bool(code.strip())
    if re.search(rf"^\s*(?:async\s+)?def {re.escape(symbol)}\b", code, re.MULTILINE):
        return True
    if extract_method_source(code, symbol):
        return True
    if target_class and extract_method_from_class_body(code, target_class, symbol):
        return True
    return False


def draft_looks_like_test_script(code: str, symbol: str, *, target_class: str = "") -> bool:
    """True when draft looks like pytest/script output rather than product methods."""
    if code_covers_symbol(code, symbol, target_class=target_class):
        if target_class and extract_method_from_class_body(code, target_class, symbol):
            return False
        if not _has_test_script_markers(code):
            return False

    defs = list_def_symbols(code)
    if any(name.startswith("test_") for name in defs):
        return True
    if re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]', code):
        return True
    if _has_test_script_markers(code) and not (
        target_class
        and re.search(rf"^class {re.escape(target_class)}\b", code, re.MULTILINE)
    ):
        return True
    return False


def _has_test_script_markers(code: str) -> bool:
    lower = code.lower()
    return any(marker.lower() in lower for marker in _TEST_SCRIPT_MARKERS)


def merged_preserves_target_class(merged: str, target_class: str) -> bool:
    """Product file must still define *target_class* after merge."""
    if not target_class.strip():
        return True
    return bool(
        re.search(rf"^class {re.escape(target_class.strip())}\b", merged, re.MULTILINE)
    )


def method_in_target_class(source: str, target_class: str, symbol: str) -> bool:
    """True when *symbol* is defined as a method on *target_class*."""
    cls = target_class.strip()
    sym = symbol.strip()
    if not cls or not sym:
        return True
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != cls:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == sym:
                return True
    return False
