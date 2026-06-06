"""Merge LLM-generated method snippets into existing Python source files."""
from __future__ import annotations

import ast
import re
import textwrap
from typing import Optional

CLASS_METHOD_INDENT = "    "


def extract_method_from_class_body(
    code: str,
    class_name: str,
    symbol: str,
) -> Optional[str]:
    """Extract ``def symbol`` from inside ``class class_name``."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    lines = code.splitlines()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != symbol:
                continue
            end = item.end_lineno or item.lineno
            return "\n".join(lines[item.lineno - 1 : end]).rstrip()
    return None


def extract_method_source(code: str, symbol: str) -> Optional[str]:
    """Extract a single ``def symbol`` block from *code* (any indent level)."""
    lines = code.splitlines()
    start_idx: Optional[int] = None
    def_indent = 0
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(?:async\s+)?def {re.escape(symbol)}\b", line):
            start_idx = i
            def_indent = len(line) - len(line.lstrip())
            break
    if start_idx is None:
        return None

    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= def_indent and re.match(r"^\s*(?:(?:async\s+)?def |class |@)", line):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).rstrip()


def normalize_class_method(method: str, indent: str = CLASS_METHOD_INDENT) -> str:
    """Dedent a method snippet and re-indent it as a class body member."""
    dedented = textwrap.dedent(method).strip("\n")
    out: list[str] = []
    for line in dedented.splitlines():
        out.append(f"{indent}{line}" if line.strip() else "")
    return "\n".join(out)


def remove_module_level_def(source: str, symbol: str) -> str:
    """Drop a column-0 ``def symbol`` and its body from *source*."""
    pattern = rf"^def {re.escape(symbol)}\b[\s\S]*?(?=^def |^class |\Z)"
    cleaned = re.sub(pattern, "", source, count=1, flags=re.MULTILINE)
    return cleaned.rstrip() + "\n" if cleaned.strip() else cleaned


def find_class_line_range(source: str, class_name: str) -> Optional[tuple[int, int]]:
    """Return 1-based inclusive ``(start_line, end_line)`` for *class_name*."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _find_class_line_range_fallback(source, class_name)

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            end = node.end_lineno or node.lineno
            return node.lineno, end
    return None


def _find_class_line_range_fallback(source: str, class_name: str) -> Optional[tuple[int, int]]:
    lines = source.splitlines()
    start: Optional[int] = None
    for i, line in enumerate(lines):
        if re.match(rf"^class {re.escape(class_name)}\b", line):
            start = i + 1
            break
    if start is None:
        return None

    end = len(lines)
    for j in range(start, len(lines)):
        line = lines[j]
        if line and not line[0].isspace() and re.match(r"^(class|def)\b", line):
            end = j
            break
    else:
        end = len(lines)
    return start, end


def _method_line_range_in_class(
    source: str,
    symbol: str,
    class_start: int,
    class_end: int,
) -> Optional[tuple[int, int]]:
    lines = source.splitlines()
    start_line: Optional[int] = None
    for i in range(class_start - 1, min(class_end, len(lines))):
        if re.match(rf"^\s{{4}}(?:async\s+)?def {re.escape(symbol)}\b", lines[i]):
            start_line = i + 1
            break
    if start_line is None:
        return None

    base_indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())
    end_line = start_line
    for j in range(start_line, min(class_end, len(lines))):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if j >= start_line and indent <= base_indent and re.match(r"^\s*(?:async\s+)?def ", line):
            end_line = j
            return start_line, end_line
        end_line = j + 1
    return start_line, end_line


def _resolve_method_source(
    new_code: str,
    symbol: str,
    target_class: str = "",
) -> Optional[str]:
    """Find *symbol* in draft snippet (module-level or inside *target_class*)."""
    method = extract_method_source(new_code, symbol)
    if method:
        return method
    if target_class:
        return extract_method_from_class_body(new_code, target_class, symbol)
    return None


def merge_all_methods_from_draft(
    existing: str,
    new_code: str,
    *,
    symbols: list[str],
    target_class: str = "",
) -> str:
    """Merge each ``def`` from *new_code* into *target_class* (helpers first)."""
    result = existing
    for symbol in symbols:
        if symbol.startswith("test_"):
            continue
        if not _resolve_method_source(new_code, symbol, target_class):
            continue
        merged = merge_method_into_class(
            result,
            new_code,
            symbol=symbol,
            target_class=target_class,
        )
        if merged is not None:
            result = merged
    return merge_module_header_from_draft(result, new_code)


def merge_method_into_class(
    existing: str,
    new_code: str,
    *,
    symbol: str,
    target_class: str = "",
) -> Optional[str]:
    """Insert or replace *symbol* inside *target_class*.

    Returns ``None`` when *symbol* cannot be extracted (never replaces *existing*
    with unrelated draft content).
    """
    if not symbol.strip():
        if not existing.strip():
            return new_code
        return None

    method = _resolve_method_source(new_code, symbol, target_class)
    if not method:
        return None

    normalized = normalize_class_method(method)
    result = remove_module_level_def(existing, symbol)

    if not target_class:
        merged = result.rstrip() + "\n\n" + normalized + "\n"
        return merge_module_header_from_draft(merged, new_code)

    class_range = find_class_line_range(result, target_class)
    if not class_range:
        return None

    class_start, class_end = class_range
    method_range = _method_line_range_in_class(result, symbol, class_start, class_end)
    lines = result.splitlines(keepends=True)

    if method_range:
        start, end = method_range
        merged_lines = lines[: start - 1]
        merged_lines.append(normalized + "\n")
        merged_lines.extend(lines[end:])
        merged = "".join(merged_lines).rstrip() + "\n"
        return merge_module_header_from_draft(merged, new_code)

    insert_at = class_end
    merged_lines = lines[:insert_at]
    if merged_lines and not merged_lines[-1].endswith("\n"):
        merged_lines[-1] += "\n"
    merged_lines.append("\n")
    merged_lines.append(normalized + "\n")
    merged_lines.extend(lines[insert_at:])
    result = "".join(merged_lines).rstrip() + "\n"
    return merge_module_header_from_draft(result, new_code)


def _safe_parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _node_source(code: str, node: ast.AST) -> str:
    segment = ast.get_source_segment(code, node)
    if segment:
        return segment.strip()
    lines = code.splitlines()
    end = node.end_lineno or node.lineno
    return "\n".join(lines[node.lineno - 1 : end]).strip()


_TYPING_NAMES = frozenset(
    {
        "Any",
        "Callable",
        "Dict",
        "Iterable",
        "List",
        "Optional",
        "Sequence",
        "Tuple",
        "Union",
    }
)


def _is_module_constant_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        name = node.id
        return name.startswith("_") or name.isupper()
    return False


def _extract_draft_header_statements(new_code: str) -> list[str]:
    """Module-level imports and private/constant assignments from *new_code*."""
    tree = _safe_parse(new_code)
    if not tree:
        return []

    statements: list[str] = []
    skipped_docstring = False
    for node in tree.body:
        if not skipped_docstring and isinstance(node, ast.Expr):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                skipped_docstring = True
                continue
        skipped_docstring = True

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            statements.append(_node_source(new_code, node))
            continue

        if isinstance(node, ast.Assign) and any(
            _is_module_constant_target(t) for t in node.targets
        ):
            statements.append(_node_source(new_code, node))
            continue

        if (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_module_constant_target(node.target)
        ):
            statements.append(_node_source(new_code, node))
            continue

        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            break

    return statements


def _needed_typing_names(code: str) -> set[str]:
    needed: set[str] = set()
    for name in _TYPING_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", code):
            needed.add(name)
    return needed


def _typing_names_in_module(source: str) -> set[str]:
    tree = _safe_parse(source)
    if not tree:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _insert_before_first_class(source: str, stmt: str) -> str:
    lines = source.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r"^class \w+", line):
            block = [stmt.rstrip() + "\n", "\n"]
            return "".join(lines[:i] + block + lines[i:]).rstrip() + "\n"
    return source.rstrip() + "\n\n" + stmt.rstrip() + "\n"


def _header_insert_line_index(source: str) -> int:
    tree = _safe_parse(source)
    if not tree or not tree.body:
        return 0
    first = tree.body[0]
    if isinstance(first, ast.Expr):
        value = first.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return first.end_lineno or 1
    return 0


def _insert_at_line(source: str, line_index: int, lines_to_add: list[str]) -> str:
    lines = source.splitlines(keepends=True)
    block: list[str] = []
    if line_index > 0 and lines and lines[min(line_index, len(lines)) - 1].strip():
        block.append("\n")
    for stmt in lines_to_add:
        block.append(stmt.rstrip() + "\n")
    block.append("\n")
    return "".join(lines[:line_index] + block + lines[line_index:]).rstrip() + "\n"


def _import_statement_present(source: str, stmt: str) -> bool:
    normalized = re.sub(r"\s+", " ", stmt.strip())
    existing = re.sub(r"\s+", " ", source)
    return normalized in existing


def _merge_typing_imports(source: str, needed: set[str]) -> str:
    missing = needed - _typing_names_in_module(source)
    if not missing:
        return source

    lines = source.splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = re.match(r"^from typing import (.+)\s*$", line.strip())
        if not match:
            continue
        current = {part.strip() for part in match.group(1).split(",") if part.strip()}
        merged = ", ".join(sorted(current | missing))
        lines[i] = f"from typing import {merged}\n"
        return "".join(lines).rstrip() + "\n"

    insert_at = _header_insert_line_index(source)
    import_line = f"from typing import {', '.join(sorted(missing))}"
    return _insert_at_line(source, insert_at, [import_line])


def _constant_names_in_assign(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _replace_or_insert_constant(source: str, name: str, stmt: str) -> str:
    tree = _safe_parse(source)
    if tree:
        for node in tree.body:
            if name not in _constant_names_in_assign(node):
                continue
            lines = source.splitlines(keepends=True)
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            replacement = [stmt.rstrip() + "\n"]
            if end < len(lines):
                replacement.append("\n")
            return "".join(lines[:start] + replacement + lines[end:]).rstrip() + "\n"
    return _insert_before_first_class(source, stmt)


def _apply_draft_constants(source: str, draft_statements: list[str]) -> str:
    result = source
    for stmt in draft_statements:
        tree = _safe_parse(stmt)
        if not tree or len(tree.body) != 1:
            continue
        node = tree.body[0]
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        names = _constant_names_in_assign(node)
        if not names or not all(_is_module_constant_target(ast.Name(id=n)) for n in names):
            continue
        for name in names:
            result = _replace_or_insert_constant(result, name, stmt)
    return result


def _apply_draft_imports(source: str, draft_statements: list[str]) -> str:
    imports = [
        stmt
        for stmt in draft_statements
        if stmt.startswith("import ") or stmt.startswith("from ")
    ]
    if not imports:
        return source

    to_add: list[str] = []
    for stmt in imports:
        if _import_statement_present(source, stmt):
            continue
        to_add.append(stmt)
    if not to_add:
        return source

    insert_at = _header_insert_line_index(source)
    return _insert_at_line(source, insert_at, to_add)


def merge_module_header_from_draft(existing: str, new_code: str) -> str:
    """Merge draft module imports/constants and inferred typing imports into *existing*."""
    if not existing.strip() or not new_code.strip():
        return existing

    draft_statements = _extract_draft_header_statements(new_code)
    result = _apply_draft_constants(existing, draft_statements)
    result = _apply_draft_imports(result, draft_statements)
    needed = _needed_typing_names(new_code)
    if needed:
        result = _merge_typing_imports(result, needed)
    return result
