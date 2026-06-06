"""Planner：tech_doc 解析与路径推断（规则，无 LLM）。"""
from __future__ import annotations

import re
from typing import Iterator

from harness.types import HarnessTask

# §0.2 的依赖顺序表：| 数字 | `方法名` | 依赖 |
_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*([^|]*)\|\s*$",
    re.MULTILINE,
)
# section 标题：## 1. MemoryManager 模块
_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
# §0.1 全局顺序表：| 1 | §1 `MemoryManager` |
_MODULE_ORDER_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*§\d+\s+`([^`]+)`\s*\|",
    re.MULTILINE,
)
# §2-§7 接口定义表：| `方法签名(参数)` | 目标/功能 | ... |
# 匹配第一列为 `方法签名` 的表格行，提取方法名
_IFACE_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|",
    re.MULTILINE,
)
# 子 section 标题：### 3.1 `McpClient` 类（...）
_SUB_SECTION_RE = re.compile(
    r"^###\s+(\d+\.\d+)\s+(.+?)\s*$", re.MULTILINE
)


def extract_spec_excerpt(
    text: str,
    task_id: str,
    symbol: str,
    max_chars: int = 20000,
    target_class: str = "",
) -> str:
    """从 tech_doc 精确提取当前任务对应的接口规格行。

    提取策略：
    1. 先定位到正确的 section（按 task_id 的 section_num）
    2. 如果有 target_class，先定位到对应的子 section（如 ### 3.2 `Executor`）
    3. 找到 `symbol(` 开头的表格行
    4. 提取从该行开始到下一个 `| ` 开头的表格行之前的所有内容（即这个方法的完整规格）
    5. 额外附上子 section 标题和表头，提供上下文
    """
    section_num = task_id.split(".")[0]

    # 1. 定位到当前 section 的 body
    sec_pat = rf"^##\s+{section_num}\.\s+.+?$"
    sec_match = re.search(sec_pat, text, re.MULTILINE)
    if not sec_match:
        # 找不到 section，回退到全文搜索
        return _fallback_excerpt(text, symbol, max_chars)

    # section 结束位置：下一个 ## 标题或文档末尾
    next_sec = re.search(r"^##\s+\d+\.\s+", text[sec_match.end():], re.MULTILINE)
    sec_end = sec_match.end() + next_sec.start() if next_sec else len(text)
    sec_body = text[sec_match.start():sec_end]

    # 2. 如果有 target_class，定位到子 section（如 ### 3.2 `Executor`）
    search_body = sec_body
    sub_header = ""
    if target_class:
        sub_pat = rf"^###\s+[\d.]+\s+.*?`{re.escape(target_class)}`.*?$"
        sub_match = re.search(sub_pat, sec_body, re.MULTILINE)
        if sub_match:
            # 子 section 结束位置：下一个 ### 或 section 结束
            next_sub = re.search(r"^###\s+", sec_body[sub_match.end():], re.MULTILINE)
            sub_end = sub_match.end() + next_sub.start() if next_sub else len(sec_body)
            search_body = sec_body[sub_match.start():sub_end]
            sub_header = sec_body[sub_match.start():sub_match.end()] + "\n\n"

    # 3. 找到包含 symbol 的表格行
    row_match = None

    # 模式 A：接口定义表 — | `symbol(参数...)` | ... |
    pat_a = rf"^\|\s*`[^`]*?{re.escape(symbol)}\s*\([^`]*`\s*\|"
    row_match = re.search(pat_a, search_body, re.MULTILINE)

    # 模式 B：接口定义表 — | `async def symbol(参数...)` | ... |
    if not row_match:
        pat_b = rf"^\|\s*`async\s+def\s+{re.escape(symbol)}\s*\([^`]*`\s*\|"
        row_match = re.search(pat_b, search_body, re.MULTILINE)

    # 模式 C：依赖顺序表 — | 数字 | `symbol` | 依赖 |（§0.2 格式）
    if not row_match:
        pat_c = rf"^\|\s*\d+\s*\|\s*`{re.escape(symbol)}`\s*\|"
        row_match = re.search(pat_c, search_body, re.MULTILINE)

    # 模式 D：宽松匹配 — 任何包含 `symbol` 或 `symbol(` 的表格行
    if not row_match:
        pat_d = rf"^\|[^|]*`[^`]*{re.escape(symbol)}[^`]*`[^|]*\|"
        row_match = re.search(pat_d, search_body, re.MULTILINE)

    if not row_match:
        return _fallback_excerpt(text, symbol, max_chars)

    # 4. 提取这一行的完整内容（到下一个表格方法行之前）
    row_start = row_match.start()
    remaining = search_body[row_match.end():]
    # 下一个表格行：| ` 开头（另一个方法）或 | 数字 | ` 开头（依赖表另一行）
    next_row = re.search(r"^\|\s*(?:`|(?:\d+\s*\|\s*`))", remaining, re.MULTILINE)
    if next_row:
        row_end = row_match.end() + next_row.start()
    else:
        row_end = len(search_body)

    spec_row = search_body[row_start:row_end].strip()

    # 5. 拼接：子 section 标题 + 表头 + 当前方法的完整规格行
    header_pat = r"^\|[^`\n]*(?:接口|Interface|顺序)[^`\n]*\|.*$\n\|[-|]+\|"
    header_match = re.search(header_pat, search_body, re.MULTILINE)
    table_header = header_match.group(0) + "\n" if header_match else ""

    result = f"{sub_header}{table_header}{spec_row}"
    return result[:max_chars]


def _fallback_excerpt(text: str, symbol: str, max_chars: int) -> str:
    """回退：直接搜索 symbol 出现的位置，取前后文。"""
    m = re.search(rf"`[^`]*{re.escape(symbol)}[^`]*`", text)
    if m:
        start = max(0, m.start() - 200)
        end = min(len(text), m.end() + max_chars)
        return text[start:end]
    return text[:max_chars]


def _extract_method_name(signature: str) -> str | None:
    """从接口签名中提取方法名。

    示例：
      "__init__(self, config)" → "__init__"
      "async def call_tool(self, name)" → "call_tool"
      "get_relevant(self, query)" → "get_relevant"
      "接口" → None（表头行，跳过）
    """
    sig = signature.strip()
    # 跳过表头行
    if sig in ("接口", "Interface"):
        return None
    # 去掉 async def 前缀
    sig = re.sub(r"^async\s+def\s+", "", sig)
    # 提取方法名（括号前的部分）
    if "(" not in sig:
        return None
    name = sig.split("(")[0].strip()
    if not name or not re.match(r"^[a-zA-Z_]\w*$", name):
        return None
    return name


def _detect_module_from_subsection(sub_title: str) -> str | None:
    """从子 section 标题提取类名。

    示例：
      "`McpClient` 类（MCP 会话薄适配层）" → "McpClient"
      "`Executor` 类（MCP 执行）" → "Executor"
    """
    m = re.search(r"`([A-Z]\w+)`", sub_title)
    return m.group(1) if m else None


def parse_iface_table_tasks(
    section_num: str,
    section_title: str,
    body: str,
    *,
    global_order: int,
    cfg: dict,
) -> Iterator[HarnessTask]:
    """解析 §2-§7 的接口定义表格（| `方法签名(...)` | 目标 | ... |）。

    对于 §3 这种有子 section（### 3.1 McpClient、### 3.2 Executor）的情况，
    按子 section 分别提取，每个子 section 对应不同的 module/target_file。
    """
    # 从 section title 提取默认 module 名
    # 优先匹配反引号里的类名：
    #   "RAG Agent 编排层 — `RagOrchestrator` 类" → "RagOrchestrator"
    #   "ContextManager 模块（历史对话提取）" → "ContextManager"
    #   "PlannerAgent 类（规划）" → "PlannerAgent"
    backtick_class = re.search(r"`([A-Z]\w+)`", section_title)
    if backtick_class:
        default_module = backtick_class.group(1)
    else:
        default_module = section_title.strip().split()[0].replace("模块", "").strip()

    # 检查是否有子 section（如 §3 有 ### 3.1 和 ### 3.2）
    sub_sections = list(_SUB_SECTION_RE.finditer(body))

    if sub_sections:
        # 有子 section：按子 section 分段解析
        local_order = 0
        for si, sub in enumerate(sub_sections):
            sub_module = _detect_module_from_subsection(sub.group(2)) or default_module
            sub_start = sub.end()
            sub_end = sub_sections[si + 1].start() if si + 1 < len(sub_sections) else len(body)
            sub_body = body[sub_start:sub_end]

            for m in _IFACE_ROW_RE.finditer(sub_body):
                method_name = _extract_method_name(m.group(1))
                if not method_name:
                    continue
                local_order += 1
                task_id = f"{section_num}.{local_order}"
                target_file = default_target_file(sub_module, method_name, cfg)

                yield HarnessTask(
                    id=task_id,
                    order=global_order * 1000 + local_order,
                    module=sub_module,
                    section=f"§{section_num}",
                    symbol=method_name,
                    title=f"{sub_module}.{method_name}",
                    description=(
                        f"在 {target_file} 中实现 {sub_module}.{method_name}，"
                        f"规格见 tech_doc §{section_num}"
                    ),
                    dependencies=[],
                    target_module=target_file.replace("/", ".").replace(".py", ""),
                    target_class=sub_module,
                    target_file=target_file,
                    done_criteria=(
                        f"实现 {sub_module}.{method_name}；pytest 路径由 Evaluator 按 "
                        f"agent_rag/test/TEST_INDEX.md 解析"
                    ),
                )
    else:
        # 无子 section：直接在 body 里找接口表格行
        local_order = 0
        for m in _IFACE_ROW_RE.finditer(body):
            method_name = _extract_method_name(m.group(1))
            if not method_name:
                continue
            local_order += 1
            task_id = f"{section_num}.{local_order}"
            target_file = default_target_file(default_module, method_name, cfg)

            yield HarnessTask(
                id=task_id,
                order=global_order * 1000 + local_order,
                module=default_module,
                section=f"§{section_num}",
                symbol=method_name,
                title=f"{default_module}.{method_name}",
                description=(
                    f"在 {target_file} 中实现 {default_module}.{method_name}，"
                    f"规格见 tech_doc §{section_num}"
                ),
                dependencies=[],
                target_module=target_file.replace("/", ".").replace(".py", ""),
                target_class=default_module,
                target_file=target_file,
                done_criteria=(
                    f"实现 {default_module}.{method_name}；pytest 路径由 Evaluator 按 "
                    f"agent_rag/test/TEST_INDEX.md 解析"
                ),
            )


def default_target_file(module: str, symbol: str, cfg: dict) -> str:
    paths = cfg.get("module_paths") or {}
    if module in paths:
        return str(paths[module])
    slug = module.replace("Manager", "").replace("Agent", "").lower()
    if module in ("McpClient", "Executor"):
        impl = cfg.get("implementation_root", "../agent_rag/agent_rag")
        name = f"{module[0].lower()}{module[1:]}.py".replace("mcpclient", "mcp_client")
        return f"{impl}/mcp/{name}"
    if module == "RagOrchestrator":
        impl = cfg.get("implementation_root", "../agent_rag/agent_rag")
        return f"{impl}/orchestrator/rag_orchestrator.py"
    root = cfg.get("implementation_root", "../agent_rag/agent_rag")
    return f"{root}/{slug}/{slug}.py"


def module_order(text: str) -> list[str]:
    found = _MODULE_ORDER_RE.findall(text)
    if not found:
        return []
    found.sort(key=lambda x: int(x[0]))
    return [name for _, name in found]


def parse_section_tasks(
    section_num: str,
    section_title: str,
    body: str,
    *,
    global_order: int,
    cfg: dict,
) -> Iterator[HarnessTask]:
    """解析一个 section 的任务。

    优先用 _ROW_RE（§0.2 那种 | 数字 | `方法名` | 依赖 | 格式）。
    如果匹配不到，回退到 _IFACE_ROW_RE（§2-§7 的 | `方法签名(...)` | 目标 | ... | 格式）。
    """
    # 提取 module 名：优先匹配反引号里的类名
    backtick_class = re.search(r"`([A-Z]\w+)`", section_title)
    if backtick_class:
        module = backtick_class.group(1)
    elif section_title:
        module = section_title.strip().split()[0].replace("模块", "").strip()
    else:
        module = section_title

    # 优先尝试 §0.2 格式（| 数字 | `方法名` | 依赖 |）
    rows = list(_ROW_RE.finditer(body))
    if rows:
        for m in rows:
            local_order, symbol, deps_cell = m.group(1), m.group(2), m.group(3).strip()
            task_id = f"{section_num}.{local_order}"
            deps = []
            for part in re.findall(r"`([^`]+)`", deps_cell):
                if part != "无" and part not in deps:
                    deps.append(part)

            target_file = default_target_file(module, symbol, cfg)

            yield HarnessTask(
                id=task_id,
                order=global_order * 1000 + int(local_order),
                module=module,
                section=f"§{section_num}",
                symbol=symbol,
                title=f"{section_title}.{symbol}",
                description=(
                    f"在 {target_file} 中实现 {module}.{symbol}，"
                    f"规格见 tech_doc {task_id}；依赖：{', '.join(deps) or '无'}"
                ),
                dependencies=deps,
                target_module=target_file.replace("/", ".").replace(".py", ""),
                target_class=module,
                target_file=target_file,
                done_criteria=(
                    f"实现 {module}.{symbol}；pytest 路径由 Evaluator 按 "
                    f"agent_rag/test/TEST_INDEX.md 解析（target_class + target_symbol 或 task_id）"
                ),
            )
    else:
        # 回退到接口定义表格式（| `方法签名(...)` | 目标 | ... |）
        yield from parse_iface_table_tasks(
            section_num, section_title, body,
            global_order=global_order, cfg=cfg,
        )


def parse_02_memory(text: str, base_order: int, cfg: dict) -> list[HarnessTask]:
    m = re.search(r"###\s+0\.2\s+§1\s+MemoryManager.*?(?=###|\Z)", text, re.DOTALL)
    if not m:
        return []
    return list(parse_section_tasks("1", "MemoryManager", m.group(0), global_order=base_order, cfg=cfg))


def parse_all_tasks(text: str, cfg: dict) -> list[HarnessTask]:
    """规则解析 tech_doc → 任务列表。"""
    tasks: list[HarnessTask] = []
    tasks.extend(parse_02_memory(text, base_order=1, cfg=cfg))

    mod_order = module_order(text)
    sections = list(_SECTION_RE.finditer(text))
    for i, sec in enumerate(sections):
        num, title = sec.group(1), sec.group(2)
        if num == "0":
            continue
        start = sec.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[start:end]
        if num == "1" and any(t.get("section") == "§1" for t in tasks):
            continue
        try:
            global_order = mod_order.index(title.split()[0]) + 1 if mod_order else int(num)
        except ValueError:
            global_order = int(num)
        tasks.extend(parse_section_tasks(num, title, body, global_order=global_order, cfg=cfg))

    tasks.sort(key=lambda t: t.get("order", 0))
    return tasks
