"""Evaluator 沙箱文件工具（供 function calling 循环执行）。"""

from __future__ import annotations



import re

from pathlib import Path

from typing import Any





class EvaluatorFileTools:

    """在 product_root / package_root 下安全读文件。"""



    def __init__(

        self,

        *,

        product_root: Path,

        package_root: Path,

        max_file_chars: int | None = None,

        max_list_entries: int = 200,

    ):

        """初始化沙箱：绑定 agent_rag 与 meta_harness_rag 根目录，并构建允许访问的路径前缀列表。"""

        self.product_root = product_root.resolve()

        self.package_root = package_root.resolve()

        self.max_file_chars = max_file_chars

        self.max_list_entries = max_list_entries

        self._allowed_prefixes = self._build_allowed_prefixes()



    def _build_allowed_prefixes(self) -> list[Path]:

        """收集 test / agent_rag / config / docs 等白名单根目录（两棵 repo 根下各扫一遍）。"""

        roots: list[Path] = []

        for base in (self.product_root, self.package_root):

            for sub in ("test", "agent_rag", "config", "docs"):

                p = (base / sub).resolve()

                if p.is_dir():

                    roots.append(p)

            if base == self.product_root:

                idx = (base / "test" / "TEST_INDEX.md").resolve()

                if idx.is_file():

                    roots.append(idx.parent)

        return roots



    def _resolve_readable(self, rel_path: str) -> Path | None:

        """将相对路径解析为可读文件绝对路径；非法路径或不在白名单内则返回 None。"""

        raw = rel_path.strip().replace("\\", "/")

        if not raw or raw.startswith("/") or ":" in raw[:3]:

            return None

        if ".." in raw.split("/"):

            return None



        candidates: list[Path] = []

        for base in (self.product_root, self.package_root):

            candidates.append((base / raw).resolve())



        for path in candidates:

            if not path.is_file():

                continue

            if self._is_under_allowed(path):

                return path

        return None



    def _resolve_dir(self, rel_path: str) -> Path | None:

        """将相对路径解析为可列目录的绝对路径；空串视为 '.'。"""

        raw = rel_path.strip().replace("\\", "/") or "."

        if raw.startswith("/") or ".." in raw.split("/"):

            return None

        for base in (self.product_root, self.package_root):

            path = (base / raw).resolve()

            if path.is_dir() and self._is_under_allowed(path):

                return path

        return None



    def _is_under_allowed(self, path: Path) -> bool:

        """判断绝对路径是否落在任一白名单前缀之下。"""

        path = path.resolve()

        for root in self._allowed_prefixes:

            try:

                path.relative_to(root)

                return True

            except ValueError:

                continue

        return False



    def schema_for_prompt(self) -> str:

        """返回拼进 system 提示词的工具说明（与 openai_tool_schemas 能力一致，自然语言版）。"""

        return (

            "可用工具（通过 JSON 的 tool_calls 调用）：\n"

            "1. read_file(rel_path: str) — 读取相对路径文件全文（evaluator.fc_read_file_max_chars>0 时可截断）\n"

            "   例: test/conftest.py, test/unit/test_memory_manager_init.py, "

            "agent_rag/memory/memory_manager.py\n"

            "2. list_dir(rel_path: str) — 列出目录（默认 test/）\n"

            "3. grep_in_file(rel_path: str, pattern: str) — 在单文件内正则搜索，返回匹配行\n"

        )



    def execute(self, name: str, arguments: dict[str, Any]) -> str:

        """按工具名分发到 read_file / list_dir / grep_in_file，返回给 LLM 的文本结果。"""

        name = (name or "").strip()

        args = arguments or {}

        try:

            if name == "read_file":

                return self._read_file(str(args.get("rel_path", "")))

            if name == "list_dir":

                return self._list_dir(str(args.get("rel_path", "test")))

            if name == "grep_in_file":

                return self._grep_in_file(

                    str(args.get("rel_path", "")),

                    str(args.get("pattern", "")),

                )

            return f"未知工具: {name}"

        except Exception as e:

            return f"工具执行失败 ({name}): {e}"



    def execute_batch(self, tool_calls: list[dict[str, Any]]) -> str:

        """批量执行工具调用（JSON 协议 FC 用），最多 12 条，结果拼成多段 markdown 文本。"""

        parts: list[str] = []

        for i, call in enumerate(tool_calls[:12], 1):

            name = str(call.get("name", call.get("tool", "")))

            args = call.get("arguments") or call.get("args") or {}

            if not isinstance(args, dict):

                args = {}

            result = self.execute(name, args)

            parts.append(f"### tool_result[{i}] {name}\n{result}")

        return "\n\n".join(parts) if parts else "（无 tool_calls）"



    def _read_file(self, rel_path: str) -> str:

        """读取单个文件内容；max_file_chars 为 None 或 ≤0 时不截断。"""

        path = self._resolve_readable(rel_path)

        if path is None:

            return f"无法读取: {rel_path}（路径无效或不在允许范围内）"

        text = path.read_text(encoding="utf-8", errors="replace")

        cap = self.max_file_chars

        if cap is None or cap <= 0 or len(text) <= cap:

            return f"path={path.relative_to(self.product_root) if path.is_relative_to(self.product_root) else path}\n```\n{text}\n```"

        return (

            f"path={path}\n（截断至 {cap} 字符）\n```\n"

            f"{text[:cap]}\n…\n```"

        )



    def _list_dir(self, rel_path: str) -> str:

        """列出目录条目（file/dir 前缀 + 相对路径），超过 max_list_entries 时省略。"""

        path = self._resolve_dir(rel_path)

        if path is None:

            return f"无法列出目录: {rel_path}"

        entries: list[str] = []

        for p in sorted(path.iterdir()):

            if len(entries) >= self.max_list_entries:

                entries.append("…")

                break

            tag = "dir/" if p.is_dir() else "file"

            try:

                rel = p.relative_to(self.product_root)

            except ValueError:

                rel = p.relative_to(self.package_root) if p.is_relative_to(self.package_root) else p.name

            entries.append(f"{tag} {rel}")

        return f"目录 {path}:\n" + "\n".join(entries)



    def _grep_in_file(self, rel_path: str, pattern: str) -> str:

        """在单文件内用正则搜索，返回「行号: 行内容」列表，最多 80 条匹配。"""

        if not pattern.strip():

            return "pattern 不能为空"

        path = self._resolve_readable(rel_path)

        if path is None:

            return f"无法读取: {rel_path}"

        try:

            rx = re.compile(pattern)

        except re.error as e:

            return f"无效正则: {e}"

        lines: list[str] = []

        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):

            if rx.search(line):

                lines.append(f"{i}: {line.rstrip()}")

            if len(lines) >= 80:

                lines.append("…（最多 80 行）")

                break

        return "\n".join(lines) if lines else "（无匹配）"

