from __future__ import annotations

import re
from typing import Any, List, Optional

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    RecursiveCharacterTextSplitter = None  # type: ignore[misc, assignment]

from src.libs.splitter.base_splitter import BaseSplitter


class RecursiveSplitter(BaseSplitter):
    """Recursive character-based text splitter.
    
    This splitter uses LangChain's RecursiveCharacterTextSplitter to split text
    by trying different separators in order (paragraphs, sentences, words) while
    respecting Markdown structure elements like headers and code blocks.
    
    Design Principles Applied:
    - Pluggable: Implements BaseSplitter interface for factory instantiation.
    - Config-Driven: Reads chunk_size and chunk_overlap from settings.
    - Fail-Fast: Raises ImportError if langchain-text-splitters is not installed.
    - Graceful Degradation: Validates inputs and provides clear error messages.
    
    Attributes:
        chunk_size: Maximum size of each chunk in characters.
        chunk_overlap: Number of overlapping characters between chunks.
        separators: List of separators to try in order (defaults to Markdown-aware).
        
    Raises:
        ImportError: If langchain-text-splitters package is not installed.
    """
    
    DEFAULT_SEPARATORS = [
        "\n\n",  # Double newline (paragraphs)
        "\n",    # Single newline
        ". ",    # Sentence endings
        "! ",
        "? ",
        "; ",
        ", ",
        " ",     # Spaces
        "",      # Characters
    ]
    
    def __init__(
        self,
        settings: Any,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        separators: Optional[List[str]] = None,
        include_references: Optional[bool] = None,
        include_appendix: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize RecursiveSplitter.
        
        Args:
            settings: Application settings containing ingestion configuration.
            chunk_size: Optional override for chunk size (defaults to settings.ingestion.chunk_size).
            chunk_overlap: Optional override for overlap (defaults to settings.ingestion.chunk_overlap).
            separators: Optional list of separator strings (defaults to Markdown-aware separators).
            **kwargs: Additional parameters passed to LangChain splitter.
        
        Raises:
            ImportError: If langchain-text-splitters is not installed.
            ValueError: If chunk_size or chunk_overlap are invalid.
        """
        if RecursiveCharacterTextSplitter is None:
            raise ImportError(
                "langchain-text-splitters is not installed. "
                "Install it with: pip install langchain-text-splitters"
            )
        
        self.settings = settings
        
        # Extract configuration from settings with overrides
        try:
            ingestion_config = settings.ingestion
            self.chunk_size = chunk_size if chunk_size is not None else ingestion_config.chunk_size
            self.chunk_overlap = chunk_overlap if chunk_overlap is not None else ingestion_config.chunk_overlap
            # 是否让 References / Appendix 进入最终 chunks。
            # 优先使用手动传参；如果没有传，就尝试从 settings.ingestion 读取；
            # 如果 settings 里也没有，就默认 True，保持原行为不变。
            self.include_references = (
                include_references
                if include_references is not None
                else getattr(ingestion_config, "include_references", True)
            )
            self.include_appendix = (
                include_appendix
                if include_appendix is not None
                else getattr(ingestion_config, "include_appendix", True)
            )
        except AttributeError as e:
            raise ValueError(
                "Missing ingestion configuration in settings. "
                "Expected settings.ingestion.chunk_size and settings.ingestion.chunk_overlap"
            ) from e
        
        # Validate configuration
        if not isinstance(self.chunk_size, int) or self.chunk_size <= 0:
            raise ValueError(f"chunk_size must be a positive integer, got: {self.chunk_size}")
        
        if not isinstance(self.chunk_overlap, int) or self.chunk_overlap < 0:
            raise ValueError(f"chunk_overlap must be a non-negative integer, got: {self.chunk_overlap}")
        
        if not isinstance(self.include_references, bool):
            raise ValueError(
                f"include_references must be a bool, got: {self.include_references}"
            )

        if not isinstance(self.include_appendix, bool):
            raise ValueError(
                f"include_appendix must be a bool, got: {self.include_appendix}"
            )
        
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )
        
        self.separators = separators if separators is not None else self.DEFAULT_SEPARATORS
        
        # Initialize LangChain splitter
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            length_function=len,
            is_separator_regex=False,
            **kwargs,
        )
    
    def split_text(
        self,
        text: str,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Split text into chunks recursively.

        改进点：
        1. 先按 Markdown 标题切 section，避免 overlap 跨章节；
        2. 每个 section 内部先保护 image/table block；
        3. 普通文本仍然走 LangChain RecursiveCharacterTextSplitter；
        4. image/table block 尽量作为整体 chunk；
        5. protected block 超过 chunk_size 时，用 0 overlap 切，避免重复图片/表格 caption。
        """

        self.validate_text(text)

        try:
            sections = self._split_by_markdown_headings(text)

            # 根据开关过滤 References / Appendix
            sections = self._filter_optional_sections(sections)

            chunks: List[str] = []

            for section in sections:
                section = section.strip()
                if not section:
                    continue

                section_chunks = self._split_section_with_protected_blocks(section)
                chunks.extend(section_chunks)

            if not chunks:
                chunks = [text]

            chunks = self._postprocess_chunks(chunks)

            # 合并过短的纯标题 chunk，例如：
            # ## Abstract + 摘要正文
            # ## 3 Setup + ## 3.1 Low Resource Datasets
            chunks = self._merge_short_heading_chunks(chunks)

            self.validate_chunks(chunks)

            return chunks

        except Exception as e:
            raise RuntimeError(
                f"RecursiveSplitter failed to split text: {e}. "
                f"Text length: {len(text)}, chunk_size: {self.chunk_size}, "
                f"chunk_overlap: {self.chunk_overlap}"
            ) from e
        
    def _filter_optional_sections(self, sections: List[str]) -> List[str]:
        """Filter References / Appendix sections according to config.

        include_references=False:
            删除 References 及其后续参考文献内容，直到遇到 Appendix。

        include_appendix=False:
            删除 Appendix / A Dataset Statistics / B Qualitative Examples 等附录内容。

        注意：
            这里是在 section 层面过滤，而不是 chunk 层面过滤。
            因为 References / Appendix 本质是文档结构，不应该等切成 chunk 后再删。
        """

        if self.include_references and self.include_appendix:
            return sections

        filtered: List[str] = []

        in_references = False
        in_appendix = False
        seen_references = False

        for section in sections:
            section = section.strip()
            if not section:
                continue

            heading = self._first_nonempty_line(section)

            is_references = self._is_references_heading(heading)
            is_appendix = self._is_appendix_heading(
                heading,
                allow_lettered_appendix=seen_references or in_appendix,
            )

            # 进入 References 区域
            if is_references:
                in_references = True
                in_appendix = False
                seen_references = True

                if self.include_references:
                    filtered.append(section)

                continue

            # 进入 Appendix 区域
            if is_appendix:
                in_appendix = True
                in_references = False

                if self.include_appendix:
                    filtered.append(section)

                continue

            # 当前处于 References 区域
            if in_references:
                if self.include_references:
                    filtered.append(section)
                continue

            # 当前处于 Appendix 区域
            if in_appendix:
                if self.include_appendix:
                    filtered.append(section)
                continue

            # 普通正文区域
            filtered.append(section)

        return filtered
    
    def _is_references_heading(self, heading_line: str) -> bool:
        """Return True if heading is References / Bibliography."""

        if not heading_line:
            return False

        text = self._normalize_heading_text(heading_line).lower()

        return text in {
            "references",
            "reference",
            "bibliography",
        }
    
    def _is_appendix_heading(
        self,
        heading_line: str,
        allow_lettered_appendix: bool = False,
    ) -> bool:
        """Return True if heading looks like Appendix.

        支持：
            ## Appendix
            ## Appendix A
            ## A Dataset Statistics
            ## B Qualitative Examples

        其中 A/B 这种字母附录标题比较容易误判，
        所以只有在 References 之后或已经进入 Appendix 区域后才允许识别。
        """

        if not heading_line:
            return False

        text = self._normalize_heading_text(heading_line)
        lower = text.lower()

        # 显式 Appendix 标题
        if lower == "appendix" or lower.startswith("appendix "):
            return True

        # ACL 论文常见附录标题：
        # A Dataset Statistics
        # B Qualitative Examples
        #
        # 为了避免误判正文标题，只有在 references 后面才启用。
        if allow_lettered_appendix:
            if re.match(r"^[A-Z]\s+.+", text):
                return True

        return False
    
    def _normalize_heading_text(self, heading_line: str) -> str:
        """Normalize Markdown heading text.

        Examples:
            ## **References** -> References
            ## **A Dataset Statistics** -> A Dataset Statistics
            ## OpenAI. 2023. Gpt-4 technical report. -> OpenAI. 2023. Gpt-4 technical report.
        """

        if not heading_line:
            return ""

        text = heading_line.strip()

        # 去掉 Markdown heading 井号
        text = re.sub(r"^#{1,6}\s+", "", text).strip()

        # 去掉常见 Markdown 强调符号
        text = text.replace("*", "").replace("_", "").strip()

        # 去掉末尾多余冒号
        text = text.rstrip(":").strip()

        return text
        
    def _merge_short_heading_chunks(self, chunks: List[str]) -> List[str]:
        """Merge very short heading-only chunks into the following chunk.

        目的：
            避免出现只有一个标题的短 chunk，例如：
                ## **Abstract**
                ## **3 Setup**
                ## **A Dataset Statistics**

        保守策略：
            1. 不合并一级文档标题；
            2. 只合并很短的纯标题 chunk；
            3. 如果下一个 chunk 也是编号标题，只允许 parent -> child 合并，
            例如 3 -> 3.1，4.2 -> 4.2.1；
            4. 不合并异常倒退标题，例如 6 -> 4.4。
        """

        if not chunks:
            return []

        merged: List[str] = []
        i = 0

        while i < len(chunks):
            current = chunks[i].strip()

            if not current:
                i += 1
                continue

            # 最后一个 chunk 没有后继，不能合并
            if i == len(chunks) - 1:
                merged.append(current)
                break

            next_chunk = chunks[i + 1].strip()

            if self._should_merge_short_heading_chunk(current, next_chunk):
                merged.append(current + "\n\n" + next_chunk)
                i += 2
                continue

            merged.append(current)
            i += 1

        return merged
        
    def _split_by_markdown_headings(self, text: str) -> List[str]:
        """Split text into sections by Markdown headings.

        让每个 Markdown 标题尽量成为 section 开头，避免 overlap 跨章节。
        """

        if not text:
            return []

        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

        heading_pattern = re.compile(
            r"(?=^#{1,6}\s+)",
            flags=re.MULTILINE,
        )

        sections = [
            part.strip()
            for part in heading_pattern.split(text)
            if part.strip()
        ]

        return sections if sections else [text]
    
    def _should_merge_short_heading_chunk(
        self,
        current_chunk: str,
        next_chunk: str,
    ) -> bool:
        """Return True if current short heading chunk should be merged with next chunk."""

        if not current_chunk or not next_chunk:
            return False

        # 只处理纯标题 chunk
        if not self._is_heading_only_chunk(current_chunk):
            return False

        # 太长的标题块不合并
        if len(current_chunk) > 120:
            return False

        current_heading = self._first_nonempty_line(current_chunk)
        next_heading = self._first_nonempty_line(next_chunk)

        if not current_heading:
            return False

        # 不合并一级文档标题：
        # # Paper Title
        # 这种通常单独保留更清楚
        if re.match(r"^#\s+", current_heading):
            return False

        # 如果下一个 chunk 不是标题，安全合并
        # 例如：
        # ## Abstract
        # Large Language Models...
        if not self._is_markdown_heading(next_heading):
            return True

        # 如果下一个 chunk 也是标题，需要判断编号关系
        current_num = self._extract_heading_number(current_heading)
        next_num = self._extract_heading_number(next_heading)

        # 情况一：
        # ## 3 Setup
        # ## 3.1 Low Resource Datasets
        # 可以合并，因为 3.1 是 3 的子节
        if current_num and next_num:
            return self._is_child_section_number(
                parent=current_num,
                child=next_num,
            )

        # 情况二：
        # ## A Dataset Statistics
        # 后面可能是表格或者子标题，允许合并到后续内容
        # 但如果两个都是无编号标题，保守起见不合并
        if current_num is None and next_num is None:
            return False

        # 情况三：
        # 当前是无编号标题，后面是普通编号标题，不合并
        # 避免把 References / Appendix 等和正文编号标题误合并
        return False
    
    def _is_heading_only_chunk(self, chunk: str) -> bool:
        """Return True if a chunk contains only Markdown heading lines."""

        lines = [line.strip() for line in chunk.splitlines() if line.strip()]

        if not lines:
            return False

        return all(self._is_markdown_heading(line) for line in lines)
    
    def _first_nonempty_line(self, text: str) -> str:
        """Return first non-empty line."""

        for line in text.splitlines():
            s = line.strip()
            if s:
                return s

        return ""
    
    def _extract_heading_number(self, heading_line: str) -> Optional[str]:
        """Extract section number from Markdown heading.

        Examples:
            ## **3 Setup** -> "3"
            ## **3.1 Low Resource Datasets** -> "3.1"
            ## **4.2.1 Round Trip Filtration** -> "4.2.1"
        """

        if not heading_line:
            return None

        # 去掉 Markdown heading 井号
        text = re.sub(r"^#{1,6}\s+", "", heading_line).strip()

        # 去掉常见 Markdown 强调符号
        text = text.replace("*", "").replace("_", "").strip()

        match = re.match(r"^(\d+(?:\.\d+)*)\b", text)

        if match:
            return match.group(1)

        return None
    
    def _is_child_section_number(self, parent: str, child: str) -> bool:
        """Return True if child is a subsection of parent.

        Examples:
            3 -> 3.1       True
            4.2 -> 4.2.1  True
            6 -> 4.4      False
            4 -> 5        False
        """

        if not parent or not child:
            return False

        return child.startswith(parent + ".")
    
    def _split_section_with_protected_blocks(self, section: str) -> List[str]:
        """Split one section while protecting image/table blocks.

        普通文本：
            用 self._splitter 正常递归切分，有 overlap。

        image/table protected block：
            尽量整体保留；
            如果太长，再用 0 overlap 切分，避免 caption / image token 重复。
        """

        blocks = self._split_into_protected_blocks(section)

        chunks: List[str] = []

        for block_type, block_text in blocks:
            block_text = block_text.strip()
            if not block_text:
                continue

            if block_type == "normal":
                normal_chunks = self._splitter.split_text(block_text)
                chunks.extend(normal_chunks or [block_text])
            else:
                protected_chunks = self._split_protected_block(block_text)
                chunks.extend(protected_chunks)

        return chunks

    def _postprocess_chunks(self, chunks: List[str]) -> List[str]:
        """Clean chunk boundary artifacts caused by character overlap."""

        cleaned_chunks: List[str] = []

        for chunk in chunks:
            if not chunk:
                continue

            chunk = chunk.strip()

            # 去掉 overlap 导致的 chunk 开头孤立标点
            # 不删 #、-、|、[，避免破坏标题、列表、表格、图片标记。
            chunk = re.sub(
                r"^[\s\.,;:!?，。；：！？]+",
                "",
                chunk,
            ).strip()

            # 压缩过多空行
            chunk = re.sub(r"\n{3,}", "\n\n", chunk)

            # 压缩行内多余空格
            chunk = re.sub(r"[ \t]{2,}", " ", chunk)

            if chunk:
                cleaned_chunks.append(chunk)

        return cleaned_chunks
    
    def _split_into_protected_blocks(self, text: str) -> List[tuple[str, str]]:
        """Split text into normal / image / table blocks.

        返回：
            [
                ("normal", "..."),
                ("image", "[IMAGE: ...] ... Figure 1: ..."),
                ("table", "|...| ... Table 1: ..."),
            ]
        """

        lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()

        blocks: List[tuple[str, str]] = []
        normal_buffer: List[str] = []

        def flush_normal() -> None:
            nonlocal normal_buffer
            if normal_buffer:
                normal_text = "\n".join(normal_buffer).strip()
                if normal_text:
                    blocks.append(("normal", normal_text))
                normal_buffer = []

        i = 0
        while i < len(lines):
            line = lines[i]
            s = line.strip()

            # 1. Image block
            if self._is_image_line(s):
                flush_normal()
                image_block, next_i = self._take_image_block(lines, i)
                blocks.append(("image", image_block.strip()))
                i = next_i
                continue

            # 2. Table block
            if self._looks_like_table_start(lines, i):
                flush_normal()
                table_block, next_i = self._take_table_block(lines, i)
                blocks.append(("table", table_block.strip()))
                i = next_i
                continue

            normal_buffer.append(line)
            i += 1

        flush_normal()

        return blocks
    
    def _is_image_line(self, stripped_line: str) -> bool:
        """Return True if line is an image token line."""

        return bool(re.match(r"^\[IMAGE:\s*[^\]]+\]\s*$", stripped_line))
    
    def _take_image_block(
        self,
        lines: List[str],
        start_idx: int,
    ) -> tuple[str, int]:
        """Take an image block from lines.

        保护范围：
        1. 一个或多个连续 [IMAGE: xxx]
        2. picture OCR:
        **----- Start of picture text -----**
        ...
        **----- End of picture text -----**
        3. Figure caption:
        Figure 1: ...
        """

        block: List[str] = []

        i = start_idx
        in_picture_text = False
        in_caption = False

        while i < len(lines):
            line = lines[i]
            s = line.strip()

            # caption 已经开始后，遇到空行就结束 image block
            if in_caption:
                if not s:
                    block.append(line)
                    i += 1
                    break

                # 遇到新标题 / 表格 / 新图片，不继续吞
                if self._is_markdown_heading(s) or self._looks_like_table_start(lines, i):
                    break

                block.append(line)
                i += 1
                continue

            # 空行：图片块内部允许保留
            if not s:
                block.append(line)
                i += 1
                continue

            # [IMAGE: xxx]
            if self._is_image_line(s):
                block.append(line)
                i += 1
                continue

            # picture OCR 开始
            if self._is_picture_text_start(s):
                in_picture_text = True
                block.append(line)
                i += 1
                continue

            # picture OCR 内部
            if in_picture_text:
                block.append(line)

                if self._is_picture_text_end(s):
                    in_picture_text = False

                i += 1
                continue

            # Figure caption
            if self._is_figure_caption(s):
                in_caption = True
                block.append(line)
                i += 1
                continue

            # 其他普通正文：image block 到此结束
            break

        return "\n".join(block), i
    
    def _is_picture_text_start(self, stripped_line: str) -> bool:
        return "----- Start of picture text -----" in stripped_line


    def _is_picture_text_end(self, stripped_line: str) -> bool:
        return "----- End of picture text -----" in stripped_line


    def _is_figure_caption(self, stripped_line: str) -> bool:
        """Figure caption line.

        支持：
        Figure 1:
        Fig. 1:
        FIGURE 1:
        """

        return bool(
            re.match(
                r"^(Figure|Fig\.)\s*\d+[A-Za-z]?\s*[:.]",
                stripped_line,
                flags=re.IGNORECASE,
            )
        )
    
    def _is_table_line(self, stripped_line: str) -> bool:
        """Return True if line looks like a Markdown table row."""

        if not stripped_line:
            return False

        # Markdown 表格通常含 |
        if "|" not in stripped_line:
            return False

        # 避免把普通 URL 或公式误判得太宽
        # 至少要有两个 |，或者是 |---| 这种 separator
        return stripped_line.count("|") >= 2
    
    def _looks_like_table_start(self, lines: List[str], idx: int) -> bool:
        """Detect Markdown table start.

        例子：
            ||**CovidQA**||
            |---|---|---|
            |**Setup**|**Exact Match**|**F1 Score**|
        """

        if idx >= len(lines):
            return False

        s = lines[idx].strip()

        if not self._is_table_line(s):
            return False

        # 向后看 1-4 行，只要看到 Markdown table separator，就认为是表格开始
        for j in range(idx + 1, min(idx + 5, len(lines))):
            t = lines[j].strip()

            if not t:
                continue

            if self._is_markdown_table_separator(t):
                return True

            if not self._is_table_line(t):
                break

        return False
    
    def _is_markdown_table_separator(self, stripped_line: str) -> bool:
        """Detect Markdown table separator line.

        支持：
            |---|---|
            |:---|---:|
            |||| 
        """

        if "|" not in stripped_line:
            return False

        if "---" in stripped_line:
            return True

        # 有些 PyMuPDF4LLM 表格会出现 |||| 作为空分隔行
        if re.fullmatch(r"\|+", stripped_line):
            return True

        return False
    
    def _take_table_block(
        self,
        lines: List[str],
        start_idx: int,
    ) -> tuple[str, int]:
        """Take a Markdown table block with its caption.

        保护范围：
        1. 连续 Markdown table rows；
        2. 表格后的空行；
        3. 紧跟的 Table caption。
        """

        block: List[str] = []
        i = start_idx

        # 1. 收集连续 table 行和表格内部空行
        while i < len(lines):
            s = lines[i].strip()

            if not s:
                block.append(lines[i])
                i += 1
                continue

            if self._is_table_line(s):
                block.append(lines[i])
                i += 1
                continue

            break

        # 2. 跳过并保留 caption 前的空行
        while i < len(lines) and not lines[i].strip():
            block.append(lines[i])
            i += 1

        # 3. 如果紧跟 Table caption，把 caption 也并入 table block
        if i < len(lines) and self._is_table_caption(lines[i].strip()):
            block.append(lines[i])
            i += 1

            # caption 可能换行，继续吞到空行或新标题/新表格/新图片前
            while i < len(lines):
                s = lines[i].strip()

                if not s:
                    block.append(lines[i])
                    i += 1
                    break

                if (
                    self._is_markdown_heading(s)
                    or self._is_image_line(s)
                    or self._looks_like_table_start(lines, i)
                ):
                    break

                block.append(lines[i])
                i += 1

        return "\n".join(block), i
    
    def _is_table_caption(self, stripped_line: str) -> bool:
        """Table caption line.

        支持：
        Table 1:
        TABLE 1:
        """

        return bool(
            re.match(
                r"^Table\s*\d+[A-Za-z]?\s*[:.]",
                stripped_line,
                flags=re.IGNORECASE,
            )
        )
    
    def _is_markdown_heading(self, stripped_line: str) -> bool:
        """Return True if line is a Markdown heading."""

        return bool(re.match(r"^#{1,6}\s+", stripped_line))
    
    def _split_protected_block(self, block_text: str) -> List[str]:
        """Split protected block.

        如果 protected block 没超过 chunk_size，整体保留。
        如果超过 chunk_size，用 0 overlap 切分，避免重复图片 token / table caption。
        """

        block_text = block_text.strip()

        if not block_text:
            return []

        if len(block_text) <= self.chunk_size:
            return [block_text]

        no_overlap_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=0,
            separators=self.separators,
            length_function=len,
            is_separator_regex=False,
        )

        return no_overlap_splitter.split_text(block_text) or [block_text]
    
    



"""Recursive Splitter implementation using LangChain.

This module provides a recursive character-based text splitting strategy
that respects document structure (headers, code blocks) and splits text
hierarchically to maintain semantic coherence.
使用LangChain实现递归文本分割，按层级结构分割文本以保持语义连贯性
"""

"""


class RecursiveSplitter(BaseSplitter):
    Recursive character-based text splitter.
    
    This splitter uses LangChain's RecursiveCharacterTextSplitter to split text
    by trying different separators in order (paragraphs, sentences, words) while
    respecting Markdown structure elements like headers and code blocks.
    
    Design Principles Applied:
    - Pluggable: Implements BaseSplitter interface for factory instantiation.
    - Config-Driven: Reads chunk_size and chunk_overlap from settings.
    - Fail-Fast: Raises ImportError if langchain-text-splitters is not installed.
    - Graceful Degradation: Validates inputs and provides clear error messages.
    
    Attributes:
        chunk_size: Maximum size of each chunk in characters.
        chunk_overlap: Number of overlapping characters between chunks.
        separators: List of separators to try in order (defaults to Markdown-aware).
        
    Raises:
        ImportError: If langchain-text-splitters package is not installed.
    
    # 公式新加
    HEADER_RE = re.compile(r"^\s*#{1,6}\s+")
    EQ_NUM_RE = re.compile(r"\(\d+\)\s*$")
    LATEX_ENV_RE = re.compile(
        r"\\begin\{(?:equation|align|gather|multline)\}"
        r"|\\end\{(?:equation|align|gather|multline)\}"
        r"|\\\[|\\\]|\\frac|\\sum|\\int|\\cos|\\sin|\\log"
    )
    MATH_SYMBOL_RE = re.compile(r"[=+\-*/^_{}\\|∈∑∫≤≥≈]")
    FORMULA_SEPARATORS = [
        "\n\n",
        "\n",
        " ",
        "",
    ]

    DEFAULT_SEPARATORS = [
        "\n\n",  # Double newline (paragraphs)
        "\n",    # Single newline
        ". ",    # Sentence endings
        "! ",
        "? ",
        "; ",
        ", ",
        " ",     # Spaces
        "",      # Characters
    ]
    
    def __init__(
        self,
        settings: Any,
        chunk_size: Optional[int] = None,  # 块大小
        chunk_overlap: Optional[int] = None,  # 重叠大小
        separators: Optional[List[str]] = None,  # 分隔符
        formula_aware: bool = True,
        formula_context_before: int = 1,
        formula_context_after: int = 1,
        **kwargs: Any,
    ) -> None:
        Initialize RecursiveSplitter.
        
        Args:
            settings: Application settings containing ingestion configuration.
            chunk_size: Optional override for chunk size (defaults to settings.ingestion.chunk_size).
            chunk_overlap: Optional override for overlap (defaults to settings.ingestion.chunk_overlap).
            separators: Optional list of separator strings (defaults to Markdown-aware separators).
            **kwargs: Additional parameters passed to LangChain splitter.
        
        Raises:
            ImportError: If langchain-text-splitters is not installed.
            ValueError: If chunk_size or chunk_overlap are invalid.
        
        if RecursiveCharacterTextSplitter is None:  # 检查是否安装
            raise ImportError(
                "langchain-text-splitters is not installed. "
                "Install it with: pip install langchain-text-splitters"
            )
        
        self.settings = settings
        
        # Extract configuration from settings with overrides 从带有覆盖设置的配置文件中提取配置信息
        try:
            ingestion_config = settings.ingestion
            self.chunk_size = chunk_size if chunk_size is not None else ingestion_config.chunk_size
            self.chunk_overlap = chunk_overlap if chunk_overlap is not None else ingestion_config.chunk_overlap
        except AttributeError as e:
            raise ValueError(
                "Missing ingestion configuration in settings. "
                "Expected settings.ingestion.chunk_size and settings.ingestion.chunk_overlap"
            ) from e
        
        # Validate configuration 验证配置 检查chunk_size > 0, chunk_overlap >= 0, chunk_overlap < chunk_size
        if not isinstance(self.chunk_size, int) or self.chunk_size <= 0:
            raise ValueError(f"chunk_size must be a positive integer, got: {self.chunk_size}")
        
        if not isinstance(self.chunk_overlap, int) or self.chunk_overlap < 0:
            raise ValueError(f"chunk_overlap must be a non-negative integer, got: {self.chunk_overlap}")
        
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )
        
        self.separators = separators if separators is not None else self.DEFAULT_SEPARATORS
        self.formula_aware = formula_aware
        self.formula_context_before = max(0, formula_context_before)
        self.formula_context_after = max(0, formula_context_after)
        
        # Initialize LangChain splitter 创建LangChain的RecursiveCharacterTextSplitter实例
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            length_function=len,
            is_separator_regex=False,
            **kwargs,
        )
        # 公式块走这个
        self._formula_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            length_function=len,
            is_separator_regex=False,
            **kwargs,
        )
    # 辅助方法
    def _is_markdown_header(self, line: str) -> bool:
        return bool(self.HEADER_RE.match(line.strip()))


    def _math_symbol_ratio(self, text: str) -> float:
        stripped = "".join(ch for ch in text if not ch.isspace())
        if not stripped:
            return 0.0
        symbol_count = len(self.MATH_SYMBOL_RE.findall(text))
        return symbol_count / len(stripped)


    def _looks_like_formula_line(self, line: str) -> bool:
        s = line.strip()
        if not s:
            return False

        # 明确的 LaTeX / display math
        if "$$" in s or self.LATEX_ENV_RE.search(s):
            return True

        # 行尾公式编号 + 数学符号
        if self.EQ_NUM_RE.search(s) and self.MATH_SYMBOL_RE.search(s):
            return True

        # 常见“短公式行”
        if len(s) <= 120 and "=" in s and self._math_symbol_ratio(s) >= 0.08:
            return True

        # 更偏数学结构的行
        if len(s) <= 120 and any(tok in s for tok in ["∈", "∑", "∫", "^", "_", "|", "\\"]):
            return True

        return False


    def _looks_like_formula_paragraph(self, text: str) -> bool:
        s = text.strip()
        if not s:
            return False

        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        if not lines:
            return False

        formula_like_lines = sum(1 for ln in lines if self._looks_like_formula_line(ln))

        # 段落里有明显公式行
        if formula_like_lines >= 1 and len(lines) <= 4:
            return True

        # 多行公式块 / 推导块
        if formula_like_lines >= max(1, (len(lines) + 1) // 2):
            return True

        # 整段符号密度偏高
        if len(s) <= 220 and self._math_symbol_ratio(s) >= 0.12 and "=" in s:
            return True

        return False


    def _split_into_paragraph_units(self, text: str) -> List[Dict[str, str]]:
        
        把文本切成基础段落单元，并把最近的 markdown header 绑定到段落上。
        返回:
            [{"header": "### xxx", "text": "paragraph text"}, ...]
        
        units: List[Dict[str, str]] = []
        current_header = ""
        buffer: List[str] = []

        def flush_buffer() -> None:
            if not buffer:
                return
            paragraph = "\n".join(buffer).strip()
            buffer.clear()
            if paragraph:
                units.append({
                    "header": current_header,
                    "text": paragraph,
                })

        for raw_line in text.splitlines():
            line = raw_line.rstrip()

            if self._is_markdown_header(line):
                flush_buffer()
                current_header = line.strip()
                continue

            if not line.strip():
                flush_buffer()
                continue

            buffer.append(line)

        flush_buffer()
        return units


    def _render_formula_unit(
        self,
        header: str,
        before_parts: List[str],
        formula_parts: List[str],
        after_parts: List[str],
    ) -> str:
        parts: List[str] = []

        if header:
            parts.append(header)

        parts.extend(before_parts)
        parts.extend(formula_parts)
        parts.extend(after_parts)

        return "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()


    def _build_semantic_units(self, text: str) -> List[Dict[str, str]]:
        
        把原始文本变成两类 unit:
        - {"kind": "normal", "text": "..."}
        - {"kind": "formula", "text": "..."}
        
        base_units = self._split_into_paragraph_units(text)
        result: List[Dict[str, str]] = []

        i = 0
        n = len(base_units)

        while i < n:
            current = base_units[i]
            current_is_formula = self._looks_like_formula_paragraph(current["text"])

            # 普通段落
            if not current_is_formula:
                # 如果下一段是公式，就先别输出当前段，让它作为公式的前文一起被吃进去
                if i + 1 < n and self._looks_like_formula_paragraph(base_units[i + 1]["text"]):
                    i += 1
                    continue

                payload = (
                    f'{current["header"]}\n{current["text"]}'.strip()
                    if current["header"] else current["text"]
                )
                result.append({"kind": "normal", "text": payload})
                i += 1
                continue

            # 公式段 / 连续公式段
            header = current["header"]
            before_parts: List[str] = []
            formula_parts: List[str] = []
            after_parts: List[str] = []

            # 向前抓解释段
            prev_idx = i - 1
            taken_before = 0
            while (
                prev_idx >= 0
                and taken_before < self.formula_context_before
                and not self._looks_like_formula_paragraph(base_units[prev_idx]["text"])
                and base_units[prev_idx]["header"] == header
            ):
                before_parts.insert(0, base_units[prev_idx]["text"])
                taken_before += 1
                prev_idx -= 1

            # 当前及后续连续公式段
            j = i
            while j < n and self._looks_like_formula_paragraph(base_units[j]["text"]):
                formula_parts.append(base_units[j]["text"])
                j += 1

            # 向后抓解释段
            next_idx = j
            taken_after = 0
            while (
                next_idx < n
                and taken_after < self.formula_context_after
                and not self._looks_like_formula_paragraph(base_units[next_idx]["text"])
                and base_units[next_idx]["header"] == header
            ):
                after_parts.append(base_units[next_idx]["text"])
                taken_after += 1
                next_idx += 1

            merged = self._render_formula_unit(
                header=header,
                before_parts=before_parts,
                formula_parts=formula_parts,
                after_parts=after_parts,
            )
            result.append({"kind": "formula", "text": merged})

            i = next_idx

        return result
    
    def _split_semantic_unit(self, unit):
        if unit["kind"] == "formula":
            return [unit["text"]]  # 公式原子化，不拆
        return self._splitter.split_text(unit["text"])# 对于文本定义的正常的LangChain迭代切分


    def _build_semantic_units(self, text: str) -> list[dict]:
        
        构建 semantic units：
        - 公式 [FORMULA X] + {...} chunk
        - 表格 [TABLE X] + Raw table content chunk，连续表格互不抓上下文
        - 普通段落 chunk
        - 标题行也可以被下一个 chunk overlap
        
        lines = text.splitlines()
        result = []
        buffer = []

        # -----------------------------
        # 新增：保存最近标题行，用于 overlap
        last_header_lines: List[str] = []

        n = len(lines)
        i = 0

        while i < n:
            line = lines[i].rstrip()

            # -----------------------------
            # 标题行处理
            if line.startswith("#"):  # 适配 # 或 ## Markdown header
                # flush 普通 buffer 前，把 overlap 加入
                if buffer:
                    normal_text = "\n".join(buffer).strip()
                    if normal_text:
                        # 将最近标题行加入普通 chunk 前面，形成 overlap
                        if last_header_lines:
                            normal_text = "\n".join(last_header_lines + [normal_text])
                        for chunk in self._split_semantic_unit({"kind": "normal", "text": normal_text}):
                            result.append({"kind": "normal", "text": chunk})
                    buffer = []

                # 保存当前标题行，用作下一个 chunk overlap
                last_header_lines = [line]
                i += 1
                continue

            # -----------------------------
            # 普通文本行累积
            if not (line.startswith("[FORMULA") or "Type: raw_formula" in line or
                    line.startswith("[TABLE") or "Type: raw_table" in line):
                buffer.append(line)
                i += 1
                continue

            # -----------------------------
            # flush buffer -> 普通 chunk（公式/表格前）
            if buffer:
                normal_text = "\n".join(buffer).strip()
                if normal_text:
                    if last_header_lines:
                        normal_text = "\n".join(last_header_lines + [normal_text])
                    for chunk in self._split_semantic_unit({"kind": "normal", "text": normal_text}):
                        result.append({"kind": "normal", "text": chunk})
                buffer = []

            # -----------------------------
            # 公式处理
            if line.startswith("[FORMULA"):
                formula_lines = [line]
                i += 1
                inside_braces = False
                while i < n:
                    next_line = lines[i].rstrip()
                    if next_line.strip().startswith("{"):
                        inside_braces = True
                    if inside_braces:
                        formula_lines.append(next_line)
                        if next_line.strip().endswith("}"):
                            i += 1
                            break
                    else:
                        if next_line.startswith("[FORMULA") or "Type: raw_formula" in next_line:
                            formula_lines.append(next_line)
                            i += 1
                        else:
                            break
                    i += 1

                # 前 context：只抓普通 chunk 的最后几行
                pre_context = []
                if result and self.formula_context_before > 0 and result[-1]["kind"] != "formula":
                    last_lines = result[-1]["text"].splitlines()
                    pre_context = last_lines[-self.formula_context_before:]

                # 后 context
                post_context = []
                taken = 0
                temp_i = i
                while temp_i < n and taken < self.formula_context_after:
                    if lines[temp_i].startswith("[FORMULA") or "Type: raw_formula" in lines[temp_i]:
                        break
                    post_context.append(lines[temp_i])
                    temp_i += 1
                    taken += 1

                formula_chunk_text = "\n".join(pre_context + formula_lines + post_context).strip()
                result.append({"kind": "formula", "text": formula_chunk_text})

                i = temp_i
                continue

            # -----------------------------
            # 表格处理
            if line.startswith("[TABLE"):
                table_lines = [line]
                i += 1
                while i < n:
                    next_line = lines[i].rstrip()
                    if next_line.startswith("[TABLE") or "Type: raw_table" in next_line:
                        table_lines.append(next_line)
                        i += 1
                    else:
                        if next_line.strip() == "" or next_line.startswith("["):
                            break
                        table_lines.append(next_line)
                        i += 1

                # 前 context：只有上一个 chunk 不是表格才抓
                pre_context = []
                if result and self.formula_context_before > 0:
                    if "[TABLE" not in result[-1]["text"]:
                        last_lines = result[-1]["text"].splitlines()
                        pre_context = last_lines[-self.formula_context_before:]

                post_context = []
                taken = 0
                temp_i = i
                while temp_i < n and taken < self.formula_context_after:
                    next_line = lines[temp_i].rstrip()
                    if "[TABLE" in next_line:
                        break
                    post_context.append(next_line)
                    temp_i += 1
                    taken += 1

                table_chunk_text = "\n".join(pre_context + table_lines + post_context).strip()
                result.append({"kind": "table", "text": table_chunk_text})

                i = temp_i
                continue

        # -----------------------------
        # flush 最后的 buffer -> 普通 chunk
        if buffer:
            normal_text = "\n".join(buffer).strip()
            if normal_text:
                if last_header_lines:
                    normal_text = "\n".join(last_header_lines + [normal_text])
                for chunk in self._split_semantic_unit({"kind": "normal", "text": normal_text}):
                    result.append({"kind": "normal", "text": chunk})

        return result

    def _split_semantic_unit(self, unit: Dict[str, str]) -> List[str]:
        splitter = self._formula_splitter if unit["kind"] == "formula" else self._splitter
        chunks = splitter.split_text(unit["text"])
        return chunks if chunks else [unit["text"]]

    def split_text(
        self,
        text: str,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:

        Split text into chunks recursively.
        
        This method splits text by trying different separators hierarchically,
        preserving document structure like Markdown headers and code blocks.
        
        Args:
            text: Input text to split. Must be a non-empty string.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Additional parameters (currently unused, reserved for future extensions).
        
        Returns:
            A list of text chunks. Each chunk respects the configured chunk_size
            and chunk_overlap. Order preserves the original text sequence.
        
        Raises:
            ValueError: If input text is invalid (empty, wrong type).
            RuntimeError: If splitting fails unexpectedly.
        
        Example:
            >>> splitter = RecursiveSplitter(settings)
            >>> chunks = splitter.split_text("# Header\\n\\nParagraph 1.\\n\\nParagraph 2.")
            >>> len(chunks)
            1  # If text fits in chunk_size
        
            
        # Validate input 确保文本有效
        self.validate_text(text)
        
        try:
            # Perform splitting  调用LangChain分割器
            chunks = self._splitter.split_text(text)
            
            # Handle edge case: LangChain may return empty list for very short text
            # 因为LangChain在判断"不需要分割"时会返回空列表，而不是返回包含原文本的单元素列表。
            if not chunks:
                chunks = [text]
            
            # Validate output 验证分割结果有效性
            self.validate_chunks(chunks)
            
            return chunks
            
        except Exception as e:
            # Catch any LangChain errors and provide context
            raise RuntimeError(
                f"RecursiveSplitter failed to split text: {e}. "
                f"Text length: {len(text)}, chunk_size: {self.chunk_size}, "
                f"chunk_overlap: {self.chunk_overlap}"
            ) from e
    def split_text(
        self,
        text: str,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        self.validate_text(text)

        try:
            if not self.formula_aware:
                chunks = self._splitter.split_text(text)
                if not chunks:
                    chunks = [text]
                self.validate_chunks(chunks)
                return chunks

            semantic_units = self._build_semantic_units(text)

            all_chunks: List[str] = []
            for unit in semantic_units:
                all_chunks.extend(self._split_semantic_unit(unit))

            if not all_chunks:
                all_chunks = [text]

            self.validate_chunks(all_chunks)
            return all_chunks

        except Exception as e:
            raise RuntimeError(
                f"RecursiveSplitter failed to split text: {e}. "
                f"Text length: {len(text)}, chunk_size: {self.chunk_size}, "
                f"chunk_overlap: {self.chunk_overlap}, formula_aware: {self.formula_aware}"
            ) from e
"""

"""Recursive Splitter implementation using LangChain.

This module provides a recursive character-based text splitting strategy
that respects document structure (headers, code blocks) and splits text
hierarchically to maintain semantic coherence.
"""

