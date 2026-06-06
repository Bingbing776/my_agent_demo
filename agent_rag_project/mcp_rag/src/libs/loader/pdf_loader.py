"""PDF Loader implementation using MarkItDown.
将PDF文件转换为标准格式的Document对象，支持文本提取和图片提取。

This module implements PDF parsing with image extraction support,
converting PDFs to standardized Markdown format with image placeholders.

Features:
- Text extraction and Markdown conversion via MarkItDown
- Image extraction and storage
- Image placeholder insertion with metadata tracking
- Graceful degradation if image extraction fails
"""

from __future__ import annotations

import pdfplumber
import re
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# MarkItDown (主解析器)
try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

# PyMuPDF4LLM 主文本解析器
try:
    import pymupdf4llm
    PYMUPDF4LLM_AVAILABLE = True
except ImportError:
    PYMUPDF4LLM_AVAILABLE = False

# PyMuPDF (图片提取)
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

# PIL (图片处理)
from PIL import Image
import io

from src.core.types import Document
from src.libs.loader.base_loader import BaseLoader

logger = logging.getLogger(__name__)


class PdfLoader(BaseLoader):
    """PDF Loader using MarkItDown for text extraction and Markdown conversion.
    
    
    This loader:
    1. Extracts text from PDF and converts to Markdown
    2. Extracts images and saves to data/images/{doc_hash}/
    3. Inserts image placeholders in the format [IMAGE: {image_id}]
    4. Records image metadata in Document.metadata.images
    
    Configuration:
        extract_images: Enable/disable image extraction (default: True)
        image_storage_dir: Base directory for image storage (default: data/images)
    
    Graceful Degradation:
        If image extraction fails, logs warning and continues with text-only parsing.
    """
    
    def __init__(
        self,
        extract_images: bool = True,
        image_storage_dir: str | Path = "data/images"
    ):
        """Initialize PDF Loader.
        
        Args:
            extract_images: Whether to extract images from PDFs.
            image_storage_dir: Base directory for storing extracted images.
        """
        # MarkItDown 是必需的，没有就报错
        if not MARKITDOWN_AVAILABLE:
            raise ImportError(
                "MarkItDown is required for PdfLoader. "
                "Install with: pip install markitdown"
            )
        
        if not PYMUPDF4LLM_AVAILABLE:
            raise ImportError(
                "PyMuPDF4LLM is required for PdfLoader. "
                "Install with: pip install pymupdf4llm"
            )
        
        self.extract_images = extract_images  # 是否提取图片
        self.image_storage_dir = Path(image_storage_dir)  # 图片存储目录
        self._markitdown = MarkItDown()  # 初始化解析器
    
    # def load(self, file_path: str | Path) -> Document:
        """Load and parse a PDF file.
        完整解析流程
        Args:
            file_path: Path to the PDF file.
            
        Returns:
            Document with Markdown text and metadata.
            
        Raises:
            FileNotFoundError: If the PDF file doesn't exist.
            ValueError: If the file is not a valid PDF.
            RuntimeError: If parsing fails critically.
        """
        """# Validate file
        path = self._validate_file(file_path)
        if path.suffix.lower() != '.pdf':
            raise ValueError(f"File is not a PDF: {path}")
        
        # Compute document hash for unique ID and image directory
        doc_hash = self._compute_file_hash(path)
        doc_id = f"doc_{doc_hash[:16]}" # 从PDF内容计算出的SHA256哈希的前16个字符
        
        # Parse PDF with MarkItDown
        try:
            pdf = fitz.open(path)
            all_text = []
            page_columns = self._detect_columns(pdf)
            for page_num, page in enumerate(pdf):
                # NEW: 根据单双栏提取文本并排序
                text_content = self._extract_text_by_columns(page, page_columns[page_num])  # MODIFIED
                all_text.append(text_content)
            pdf.close()
            text_content = "\n".join(all_text)
            # result = self._markitdown.convert(str(path))
            # text_content = result.text_content if hasattr(result, 'text_content') else str(result)
        except Exception as e:
            logger.error(f"Failed to parse PDF {path}: {e}")
            raise RuntimeError(f"PDF parsing failed: {e}") from e
        
        # Initialize metadata
        metadata: Dict[str, Any] = {
            "source_path": str(path),
            "doc_type": "pdf",
            "doc_hash": doc_hash,
        }
        
        # Extract title from first heading if available
        title = self._extract_title(text_content)
        if title:
            metadata["title"] = title
        
        # Handle image extraction (with graceful degradation)
        # 优雅降级策略
        if self.extract_images:
            try:
                text_content, images_metadata = self._extract_and_process_images(
                    path, text_content, doc_hash
                )
                if images_metadata:
                    metadata["images"] = images_metadata
            except Exception as e:
                logger.warning(
                    f"Image extraction failed for {path}, continuing with text-only: {e}"
                )
        
        return Document(
            id=doc_id,
            text=text_content,
            metadata=metadata
        )"""

    """def load(self, file_path: str | Path) -> Document:
        Load and parse a PDF file.

        # Validate file
        path = self._validate_file(file_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"File is not a PDF: {path}")

        # Compute document hash for unique ID and image directory
        doc_hash = self._compute_file_hash(path)
        doc_id = f"doc_{doc_hash[:16]}"

        # Parse PDF text with PyMuPDF4LLM
        try:
            text_content = pymupdf4llm.to_markdown(
                str(path),
                write_images=False,  # 不让 PyMuPDF4LLM 提图，避免和你自己的图片逻辑重复
            )
        except Exception as e:
            logger.error(f"Failed to parse PDF {path}: {e}")
            raise RuntimeError(f"PDF parsing failed: {e}") from e

        # Initialize metadata
        metadata: Dict[str, Any] = {
            "source_path": str(path),
            "doc_type": "pdf",
            "doc_hash": doc_hash,
            "parser": "pymupdf4llm",
        }

        # Extract title from first heading if available
        title = self._extract_title(text_content)
        if title:
            metadata["title"] = title

        # Keep your existing image extraction logic
        if self.extract_images:
            try:
                text_content, images_metadata = self._extract_and_process_images(
                    path, text_content, doc_hash
                )
                if images_metadata:
                    metadata["images"] = images_metadata
            except Exception as e:
                logger.warning(
                    f"Image extraction failed for {path}, continuing with text-only: {e}"
                )

        return Document(
            id=doc_id,
            text=text_content,
            metadata=metadata,
        )"""
    
    def load(self, file_path: str | Path) -> Document:
        """Load and parse a PDF file.

        目标：
        1. 使用 PyMuPDF4LLM 提取文本和图片；
        2. 图片文件最终重命名为旧逻辑的 {image_id}.png；
        3. Document.text 中图片位置使用旧逻辑的 [IMAGE: image_id]；
        4. metadata["images"] 的字段定义尽量完全沿用旧逻辑。
        """

        path = self._validate_file(file_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"File is not a PDF: {path}")

        doc_hash = self._compute_file_hash(path)
        doc_id = f"doc_{doc_hash[:16]}"

        metadata: Dict[str, Any] = {
            "source_path": str(path),
            "doc_type": "pdf",
            "doc_hash": doc_hash,
            "parser": "pymupdf4llm",
        }

        image_dir = self.image_storage_dir / doc_hash
        image_dir.mkdir(parents=True, exist_ok=True)

        # 清理旧图片，避免重复运行时残留旧文件影响匹配
        if self.extract_images:
            for old_image in image_dir.iterdir():
                if old_image.is_file() and old_image.suffix.lower() in {
                    ".png", ".jpg", ".jpeg", ".webp"
                }:
                    try:
                        old_image.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to remove old image {old_image}: {e}")

        # PyMuPDF4LLM 会用这个作为输出图片名前缀
        # 例如：2024.acl-long.93.pdf-0002-00.png
        image_filename_prefix = path.name

        # ------------------------------------------------------------
        # 1. 用 PyMuPDF4LLM 按页解析 PDF
        # ------------------------------------------------------------
        try:
            try:
                page_chunks = pymupdf4llm.to_markdown(
                    str(path),
                    page_chunks=True,
                    write_images=self.extract_images,
                    image_path=str(image_dir),
                    image_format="png",
                    image_dpi=150,
                    filename=image_filename_prefix,
                    header=False,
                    footer=False,
                )
            except TypeError:
                # 兼容部分 PyMuPDF4LLM 版本使用 dpi 参数
                page_chunks = pymupdf4llm.to_markdown(
                    str(path),
                    page_chunks=True,
                    write_images=self.extract_images,
                    image_path=str(image_dir),
                    image_format="png",
                    dpi=150,
                    filename=image_filename_prefix,
                    header=False,
                    footer=False,
                )

        except Exception as e:
            logger.error(f"Failed to parse PDF {path}: {e}")
            raise RuntimeError(f"PDF parsing failed: {e}") from e

        # ------------------------------------------------------------
        # 2. 逐页构建 text 和 images metadata
        # ------------------------------------------------------------
        text_pages: List[str] = []
        images_metadata: List[Dict[str, Any]] = []

        markdown_image_pattern = re.compile(
            r"!\[[^\]]*\]\([^\)]*\.(?:png|jpg|jpeg|webp)[^\)]*\)",
            flags=re.IGNORECASE,
        )

        omitted_picture_pattern = re.compile(
            r"\*\*==>\s*picture\s*\[\d+\s*x\s*\d+\]\s*intentionally omitted\s*<==\*\*",
            flags=re.IGNORECASE,
        )

        for page_idx, page_chunk in enumerate(page_chunks):
            page_number = page_idx + 1
            page_text = (page_chunk.get("text", "") or "").strip()

            # 先清理 PDF 页脚、页码、版权信息
            page_text = self._clean_pdf_page_noise(page_text)

            page_images = page_chunk.get("images", []) or []

            # 有些版本 page_chunk["images"] 可能不稳定，
            # 所以同时根据 page_text 里的 Markdown 图片链接 / omitted marker 估算图片数。
            markdown_refs = markdown_image_pattern.findall(page_text)
            omitted_refs = omitted_picture_pattern.findall(page_text)

            expected_image_count = max(
                len(page_images),
                len(markdown_refs) + len(omitted_refs),
            )

            if not self.extract_images:
                expected_image_count = 0

            # img_index 保持 0-based，和旧代码 position["index"] 一致
            for img_index in range(expected_image_count):
                # image_id 的 sequence 保持旧逻辑：img_index + 1
                image_id = self._generate_image_id(
                    doc_hash=doc_hash,
                    page=page_number,
                    sequence=img_index + 1,
                )

                # 找到 PyMuPDF4LLM 写出的图片，并重命名为旧逻辑文件名
                # 返回：
                # image_path: 重命名后的路径，例如 d0af5bfe_2_1.png
                # original_filename: 重命名前的原始文件名，例如 2024.acl-long.93.pdf-0002-00.png
                image_path, original_filename = self._find_and_rename_pymupdf4llm_image_file(
                    image_dir=image_dir,
                    page_number=page_number,
                    zero_based_image_index=img_index,
                    image_id=image_id,
                    source_pdf_name=path.name,
                )

                width, height = 0, 0
                relative_path = None

                if image_path is not None:
                    try:
                        relative_path = image_path.relative_to(Path.cwd())
                    except ValueError:
                        relative_path = image_path.absolute()

                    try:
                        with Image.open(image_path) as img:
                            width, height = img.size
                    except Exception:
                        width, height = 0, 0

                token = f"[IMAGE: {image_id}]"

                # 把当前页里的一个图片引用替换成 [IMAGE: image_id]
                page_text = self._replace_one_image_reference_in_page_text(
                    page_text=page_text,
                    token=token,
                    original_filename=original_filename,
                )

                # metadata 字段定义沿用旧逻辑
                image_metadata = {
                    "id": image_id,
                    "path": str(relative_path) if relative_path is not None else "",
                    "page": page_number,
                    "text_offset": None,       # 全文拼接后统一回填
                    "text_length": len(token), # 旧逻辑：len("[IMAGE: xxx]")
                    "position": {
                        "width": width,
                        "height": height,
                        "page": page_number,
                        "index": img_index,     # 0-based，和旧逻辑一致
                    },
                }

                images_metadata.append(image_metadata)

            text_pages.append(page_text)

        # ------------------------------------------------------------
        # 3. 拼接全文
        # ------------------------------------------------------------
        text_content = "\n\n".join(page for page in text_pages if page).strip()

        # 处理跨页断词
        text_content = self._fix_hyphenated_line_breaks(text_content)

        # ------------------------------------------------------------
        # 4. 回填 text_offset / text_length
        # ------------------------------------------------------------
        for image_meta in images_metadata:
            token = f"[IMAGE: {image_meta['id']}]"
            offset = text_content.find(token)

            image_meta["text_offset"] = offset if offset >= 0 else None
            image_meta["text_length"] = len(token)

        # ------------------------------------------------------------
        # 5. 标题 / metadata
        # ------------------------------------------------------------
        title = self._extract_title(text_content)
        if title:
            metadata["title"] = title

        if images_metadata:
            metadata["images"] = images_metadata


        return Document(
            id=doc_id,
            text=text_content,
            metadata=metadata,
        )
    
    # 根据文字块坐标判断单双栏
    def _detect_columns(self, pdf: fitz.Document) -> List[str]:  # NEW
        page_columns = []
        for page in pdf:
            blocks = page.get_text("blocks")
            if not blocks:
                page_columns.append("unknown")
                continue
            x_positions = [(b[0], b[2]) for b in blocks]
            min_x = min(x0 for x0, x1 in x_positions)
            max_x = max(x1 for x0, x1 in x_positions)
            mid_x = (min_x + max_x) / 2
            left_count = sum(1 for x0, x1 in x_positions if x1 <= mid_x)
            right_count = sum(1 for x0, x1 in x_positions if x0 >= mid_x)
            if left_count > 3 and right_count > 0:
                page_columns.append("two-column")
            else:
                page_columns.append("one-column")
        print(page_columns)
        return page_columns  
    

    # 根据单双栏选择排序方式
    def _extract_text_by_columns(self, page: fitz.Page, column_type: str) -> str:
        blocks = page.get_text("blocks")
        if not blocks:
            return ""

        page_height = page.rect.height

        # 左右栏排序（原有逻辑保持不变）
        min_x = min(b[0] for b in blocks)
        max_x = max(b[2] for b in blocks)
        mid_x = (min_x + max_x) / 2
        if column_type == "one-column":
            ordered_blocks = sorted(blocks, key=lambda b: b[1])
        else:
            left_blocks = [b for b in blocks if b[0] <= mid_x]
            right_blocks = [b for b in blocks if b[0] > mid_x]
            left_blocks.sort(key=lambda b: b[1])
            right_blocks.sort(key=lambda b: b[1])
            ordered_blocks = left_blocks + right_blocks

        # =========================
        # 基础 helper
        # =========================
        def _normalize_inline(text):
            if not text:
                return ""
            return re.sub(r"\s+", " ", text).strip()

        def _num_to_level(num_str):
            clean = re.sub(r'^[\(\[]|[\)\]]$', '', num_str.strip())
            dots = clean.count('.')
            return min(dots + 2, 6)  # 1 -> ##, 1.1 -> ###, ...

        def _is_body_start(text):
            """判断文本是否像正文开头（应停止收集标题）"""
            s = _normalize_inline(text)
            if not s:
                return True

            first_word = s.split()[0] if s.split() else ""
            body_starters = {
                'This', 'We', 'The', 'In', 'To', 'For', 'And', 'But',
                'However', 'Therefore', 'Thus', 'Moreover', 'Additionally',
                'Recent', 'Previous', 'Our', 'Their', 'A', 'An'
            }
            if first_word in body_starters and len(s) > 80:
                return True

            if re.search(r'\.\s+[A-Z]', s):
                return True

            if re.search(r'\([A-Z][a-z]+\.?,?\s+\d{4}\)', s):
                return True

            return False

        def _is_new_chapter(text):
            """判断文本是否像新章节（应停止收集当前标题）"""
            s = _normalize_inline(text)
            if not s or not s[0].isupper():
                return False

            if re.match(r'^\s*\d+(?:\.\d+)*[\.\s]+\s*[A-Z]', s):
                return True

            if len(s) < 100 and '.' not in s and ',' not in s:
                first_word = s.split()[0] if s.split() else ""
                if first_word not in {'This', 'We', 'The', 'In', 'To', 'For'}:
                    return True

            return False

        # =========================
        # 公式相关 helper
        # =========================
        def _looks_like_formula_line(text):
            """判断一行是否像单行公式"""
            s = _normalize_inline(text)
            if not s:
                return False

            if any(sym in s for sym in ["=", "^", "_", "\\", "∑", "∫", "≤", "≥", "≈", "∈"]):
                return True

            if re.search(r'\b(cos|sin|tan|log|exp|min|max|sim)\b', s):
                return True

            # 只把 'Diff =' 当公式，不把单独的 'Diff' 当公式
            if re.match(r'^\s*Diff\s*=', s):
                return True

            if re.search(r'\(\d+\)\s*$', s) and re.search(r'[A-Za-z0-9)]', s):
                return True

            return False

        def _merge_equation_number_in_block(text):
            """把 block 内部单独成行的公式编号并回上一行公式"""
            if not text:
                return ""

            sub_lines = [x.strip() for x in text.splitlines() if x.strip()]
            if not sub_lines:
                return ""

            merged_lines = []
            for sub_line in sub_lines:
                if re.match(r'^\(\d+\)$', sub_line) and merged_lines and _looks_like_formula_line(merged_lines[-1]):
                    # 提取编号数字
                    eq_num = re.search(r'\((\d+)\)', sub_line).group(1)
                    # 如果上一行还没有 [FORMULA x] 标记，则添加
                    if not merged_lines[-1].strip().startswith('[FORMULA'):
                        merged_lines[-1] = f"[FORMULA {eq_num}] " + merged_lines[-1].rstrip() + " " + sub_line
                    else:
                        merged_lines[-1] = merged_lines[-1].rstrip() + " " + sub_line
                else:
                    merged_lines.append(sub_line)

            return "\n".join(merged_lines)

        def _looks_like_formula_fragment(text):
            """判断一行是否像多行公式中的碎片"""
            s = _normalize_inline(text)
            if not s:
                return False

            if re.match(r'^\(\d+\)$', s):          # (4)
                return True
            if re.match(r'^\d+$', s):              # 1
                return True
            if re.match(r'^[A-Za-z]$', s):         # X
                return True
            if re.match(r'^\|[A-Za-z]+\|$', s):    # |B|, |H|
                return True
            if re.match(r'^[A-Za-z]+\s*=$', s):    # Diff =
                return True
            if re.search(r'[∈=|^_\\−+\-*/]', s) and len(s) <= 20:
                return True

            return False

        def _collect_formula_lines_from_md_lines(md_lines, current_line, max_back=12):
            """
            只在当前行带公式编号，且前面已经出现一串公式碎片时，
            把这些碎片回收成 raw formula block。
            这样不会把 (1)(2)(3) 那种单行公式误包装。
            """
            s = _normalize_inline(current_line)
            if not s:
                return None

            if not re.search(r'\(\d+\)\s*$', s):
                return None
            if not _looks_like_formula_line(s):
                return None

            collected = [current_line]
            fragment_count = 0
            steps = 0

            while md_lines and steps < max_back:
                prev = _normalize_inline(md_lines[-1])
                if _looks_like_formula_fragment(prev):
                    collected.insert(0, md_lines.pop())
                    fragment_count += 1
                    steps += 1
                    continue
                break

            if fragment_count >= 2:
                return collected

            return None
        
        def _render_formula_raw_block(formula_lines):
            """
            将整个公式 block 包在一个大 {} 内，并保持所有行
            """
            # 提取公式编号
            equation_id = None
            for line in formula_lines:
                m = re.search(r'\((\d+)\)\s*$', line)
                if m:
                    equation_id = m.group(1)
                    break

            # 整个公式 block 内容
            formula_content = "\n".join([line.rstrip() for line in formula_lines if line.strip()])

            # 用一个大 {} 包裹整个公式 block
            formula_content_wrapped = "{" + formula_content + "}"

            parts = [f"[FORMULA {equation_id}]" if equation_id else "[FORMULA]"]
            parts.append("Type: raw_formula")
            parts.append("Raw formula content:")
            parts.append(formula_content_wrapped)

            return "\n".join(parts)


        """def _render_formula_raw_block(formula_lines):
            # 把多行 display equation 包装成 raw formula block
            equation_id = None
            for line in formula_lines:
                m = re.search(r'\((\d+)\)\s*$', _normalize_inline(line))
                if m:
                    equation_id = m.group(1)

            parts = [f"[FORMULA {equation_id}]" if equation_id else "[FORMULA]"]
            parts.append("Type: raw_formula")
            parts.append("Raw formula content:")

            for row in formula_lines:
                row = _normalize_inline(row)
                if row:
                    parts.append(row)

            return "\n".join(parts)"""
        
    
        # =========================
        # 表格相关 helper
        # =========================
        def _looks_like_table_caption(text):
            s = _normalize_inline(text)
            if not s:
                return False
            return bool(re.match(r'^\s*Table\s+\d+\s*[:.]\s*', s, re.IGNORECASE))

        def _looks_like_wrapped_prose_line(text):
            """判断是否像双栏 PDF 里被切碎的正文短行"""
            s = _normalize_inline(text)
            if not s:
                return False

            tokens = s.split()
            if len(tokens) < 6:
                return False

            stopwords = {
                'the', 'of', 'and', 'in', 'to', 'with', 'that', 'is',
                'are', 'for', 'on', 'we', 'this', 'these', 'our'
            }
            hit = sum(tok.lower().strip('(),.:;') in stopwords for tok in tokens)

            if hit >= 2 and not re.search(r'\d', s):
                return True

            return False

        def _looks_like_table_header_line(text):
            """
            判断是否像表格表头行，兼容：
            - Target Sim.
            - Baseline Sim.
            - P > |z|
            - 以及 Table 2 这种“整行合并表头 block”
            """
            s = _normalize_inline(text)
            if not s:
                return False

            if s.startswith("#"):
                return False
            if _looks_like_table_caption(s):
                return False
            if _looks_like_formula_line(s):
                return False
            if _looks_like_formula_fragment(s):
                return False

            if re.match(r'^\d+\s*https?://', s, re.IGNORECASE):
                return False
            if re.match(r'^\d+$', s):
                return False

            # 这里不要直接调用 _is_body_start(s)
            # 因为 "Relationship Target Sim. Baseline Sim. Diff"
            # 这种合并表头会被误判成正文
            if _looks_like_wrapped_prose_line(s):
                return False

            if len(s) > 120:
                return False

            tokens = s.split()
            if not (1 <= len(tokens) <= 12):
                return False

            capitalized_tokens = sum(
                1 for t in tokens
                if t and re.match(r'^[A-Z][A-Za-z0-9.\-]*$', t)
            )
            abbrev_tokens = sum(
                1 for t in tokens
                if re.search(r'[A-Za-z]', t) and any(ch in t for ch in ['.', '>', '<', '|', '%'])
            )

            if capitalized_tokens >= 2 or abbrev_tokens >= 1:
                return True

            if len(tokens) <= 3 and s[0].isupper():
                return True

            return False
        
        def _looks_like_table_line(text):
            """判断一行是否像表格候选行（放宽规则以捕捉实验结果表格）"""
            s = _normalize_inline(text)
            if not s:
                return False

            # 放宽：只要包含至少两个数字，并且至少三个 token，就认为可能是表格行
            tokens = s.split()
            num_count = sum(1 for t in tokens if re.search(r'\d', t))
            if num_count >= 2 and len(tokens) >= 3:
                return True

            # 纯文字表头行（例如 "Setup Exact Match F1 Score"）
            if len(tokens) >= 3 and all(t[0].isupper() or t in {"Exact", "Match", "Score"} for t in tokens[:4]):
                return True

            return False

        def _collect_table_lines_from_ordered_blocks(caption_idx, max_back=40):
            """
            直接从 ordered_blocks 向前回收表格候选块。
            放宽高度限制和边界检查
            """
            collected = []
            steps = 0
            j = caption_idx - 1

            while j >= 0 and steps < max_back:
                b2 = ordered_blocks[j]
                top2, bottom2 = b2[1], b2[3]

                # 放宽页面边界限制
                if top2 < 0.01 * page_height or bottom2 > 0.99 * page_height:
                    j -= 1
                    continue

                cand = _merge_equation_number_in_block(b2[4].strip())
                cand = _normalize_inline(cand)

                if not cand:
                    j -= 1
                    continue

                if _is_table_candidate(cand):
                    collected.insert(0, cand)
                    steps += 1
                    j -= 1
                    continue

                break

            return collected

        """def _looks_like_table_line(text):
            #判断一行是否像表格候选行（表头或单元格），而不是普通正文
            s = _normalize_inline(text)
            if not s:
                return False

            if s.startswith("#"):
                return False
            if _looks_like_table_caption(s):
                return False

            # 先让表头本身也算 table candidate
            if _looks_like_table_header_line(s):
                return True

            if _looks_like_formula_line(s):
                return False
            if _looks_like_formula_fragment(s):
                return False

            # 这里也不要让合并表头被正文规则误杀
            if _looks_like_wrapped_prose_line(s):
                return False

            if _is_new_chapter(s):
                return False
            if _is_body_start(s):
                return False

            if re.match(r'^\d+\s*https?://', s, re.IGNORECASE):
                return False

            # 纯数字页码不要，但小数/百分比这种表格数值要保留
            if re.match(r'^\d+$', s):
                return False

            # 单独的数值单元格（Table 2 / Table 3 很需要）
            if re.match(r'^-?\d[\d,]*(?:\.\d+)?%?$', s):
                return True

            # 中文例子列
            if re.search(r'[\u4e00-\u9fff]', s) and '(' in s and ')' in s:
                return True

            # 短标签 / 行名 / 单元格
            tokens = s.split()
            if 1 <= len(tokens) <= 8:
                return True

            return False"""

        def _is_table_candidate(text):
            s = _normalize_inline(text)
            return _looks_like_table_line(s) or _looks_like_table_header_line(s)

        """def _collect_table_lines_from_ordered_blocks(caption_idx, max_back=40):
            
            #直接从 ordered_blocks 向前回收表格候选块。
            #不再只依赖 md_lines。
            
            collected = []
            steps = 0
            j = caption_idx - 1

            while j >= 0 and steps < max_back:
                b2 = ordered_blocks[j]
                top2, bottom2 = b2[1], b2[3]

                if top2 < 0.05 * page_height or bottom2 > 0.95 * page_height:
                    j -= 1
                    continue

                cand = _merge_equation_number_in_block(b2[4].strip())
                cand = _normalize_inline(cand)

                if not cand:
                    j -= 1
                    continue

                if _is_table_candidate(cand):
                    collected.insert(0, cand)
                    steps += 1
                    j -= 1
                    continue

                break

            return collected"""

        def _pop_recent_matching_lines(md_lines, lines):
            """
            把已经写进 md_lines 的表格候选尾部删掉，
            再用 [TABLE X] block 替换。
            """
            if not md_lines or not lines:
                return

            norm_lines = [_normalize_inline(x) for x in lines]

            if len(md_lines) >= len(norm_lines):
                tail = [_normalize_inline(x) for x in md_lines[-len(norm_lines):]]
                if tail == norm_lines:
                    del md_lines[-len(norm_lines):]
                    return

            k = len(norm_lines) - 1
            while k >= 0 and md_lines:
                if _normalize_inline(md_lines[-1]) == norm_lines[k]:
                    md_lines.pop()
                    k -= 1
                else:
                    break

        def _render_table_raw_block(caption_line, table_lines):
            """把表格原始内容包装成安全的 raw table block"""
            caption_line = _normalize_inline(caption_line)

            m = re.match(r'^\s*(Table\s+\d+)\s*[:.]?\s*(.*)$', caption_line, re.IGNORECASE)
            if m:
                table_id = m.group(1).upper()
                caption_text = m.group(2).strip()
            else:
                table_id = "TABLE"
                caption_text = caption_line.strip()

            caption_text = re.sub(r'(?<=[A-Za-z])-\s+(?=[a-z])', '', caption_text)

            parts = [f"[{table_id}]"]
            if caption_text:
                parts.append(f"Caption: {caption_text}")
            parts.append("Type: raw_table")
            parts.append("Raw table content:")

            for row in table_lines:
                row = _normalize_inline(row)
                if row:
                    parts.append(row)

            return "\n".join(parts)

        # =========================
        # 收尾 helper
        # =========================
        def _fix_hyphenated_linebreaks(text):
            if not text:
                return ""
            # word-\nnext -> wordnext
            text = re.sub(r'(?<=[A-Za-z])-\s*\n\s*(?=[a-z])', '', text)
            # word- next -> wordnext
            text = re.sub(r'(?<=[A-Za-z])-\s+(?=[a-z])', '', text)
            return text

        def _append_line_dedup(md_lines, line):
            """只做最小去重，避免紧邻重复"""
            s = _normalize_inline(line)
            if not s:
                return

            if md_lines and _normalize_inline(md_lines[-1]) == s:
                return

            md_lines.append(line)

        # =========================
        # 主循环
        # =========================
        md_lines = []
        i = 0
        while i < len(ordered_blocks):
            b = ordered_blocks[i]
            line = _merge_equation_number_in_block(b[4].strip())
            top, bottom = b[1], b[3]

            if top < 0.05 * page_height or bottom > 0.95 * page_height:
                i += 1
                continue

            if not line:
                i += 1
                continue

            if re.match(r'^\d+$', _normalize_inline(line)): #将单独数字行非公式行跳过
                prev_formulaish = bool(md_lines and _looks_like_formula_fragment(md_lines[-1]))
                next_formulaish = False
                if i + 1 < len(ordered_blocks):
                    next_line_probe = _merge_equation_number_in_block(ordered_blocks[i + 1][4].strip())
                    next_formulaish = _looks_like_formula_fragment(next_line_probe)

                if not (prev_formulaish or next_formulaish):
                    i += 1
                    continue

            """if re.match(r'^\(\d+\)$', _normalize_inline(line)):
                for j in reversed(range(len(md_lines))):
                    if "[FORMULA]" in md_lines[j] or _looks_like_formula_line(md_lines[j]):
                        # 拼接编号
                        md_lines[j] = md_lines[j].rstrip() + " " + _normalize_inline(line)
                        break
                i += 1
                continue"""

            """if _looks_like_formula_line(line):
                # 构建公式 block
                formula_block = "[FORMULA]\nType: raw_formula\nRaw formula content:\n" + line
                md_lines.append(formula_block)
                i += 1
                continue"""

            formula_lines = _collect_formula_lines_from_md_lines(md_lines, line)
            if formula_lines:
                formula_block = _render_formula_raw_block(formula_lines)
                _append_line_dedup(md_lines, formula_block)
                i += 1
                continue

            unnumbered_heading_match = re.match(
                r'^\s*(Abstract|References|Acknowledgements?|Appendix)\s*$',
                _normalize_inline(line),
                re.IGNORECASE
            )
            if unnumbered_heading_match:
                heading_text = unnumbered_heading_match.group(1).strip()
                _append_line_dedup(md_lines, "## " + heading_text)
                i += 1
                continue

            if page.number == 0 and i == 0:
                title_line = _normalize_inline(line)
                if 20 <= len(title_line) <= 300 and not title_line.endswith("."):
                    _append_line_dedup(md_lines, "# " + title_line)
                    i += 1
                    continue

            if _looks_like_table_caption(line):
                table_lines = _collect_table_lines_from_ordered_blocks(i)

                if len(table_lines) >= 3:
                    _pop_recent_matching_lines(md_lines, table_lines)
                    table_block = _render_table_raw_block(line, table_lines)
                    _append_line_dedup(md_lines, table_block)
                    i += 1
                    continue

            one_line_match = re.match(r'^\s*(\d+(?:\.\d+)*)[\.\s]+\s*([A-Z][^.]*?)\s*$', _normalize_inline(line))
            if one_line_match:
                chapter_num = one_line_match.group(1)
                title_text = _normalize_inline(one_line_match.group(2))
                level = _num_to_level(chapter_num)
                _append_line_dedup(md_lines, "#" * level + " " + title_text)
                i += 1
                continue

            chap_match = re.match(r'^\s*(\d+\.\d+)\s*$', _normalize_inline(line))
            if chap_match:
                chapter_num = chap_match.group(1)

                title_parts = []
                j = i + 1
                max_safety = 5

                while j < len(ordered_blocks) and len(title_parts) < max_safety:
                    next_b = ordered_blocks[j]
                    next_line = _merge_equation_number_in_block(next_b[4].strip())
                    next_top, next_bottom = next_b[1], next_b[3]

                    if not _normalize_inline(next_line):
                        j += 1
                        continue

                    if next_top < 0.05 * page_height or next_bottom > 0.95 * page_height:
                        break

                    if _is_new_chapter(next_line):
                        break

                    if _is_body_start(next_line):
                        break

                    title_parts.append(_normalize_inline(next_line))
                    j += 1

                if title_parts:
                    title_text = " ".join(title_parts)
                    level = _num_to_level(chapter_num)
                    _append_line_dedup(md_lines, "#" * level + " " + title_text)
                    i = j
                    continue

            _append_line_dedup(md_lines, _normalize_inline(line))
            i += 1

        text = "\n".join(md_lines)
        text = _fix_hyphenated_linebreaks(text)
        return text
    
        # return "\n".join(md_lines)
    
    def _find_and_rename_pymupdf4llm_image_file(
        self,
        image_dir: Path,
        page_number: int,
        zero_based_image_index: int,
        image_id: str,
        source_pdf_name: str,
    ) -> tuple[Optional[Path], Optional[str]]:
        """Find the image file written by PyMuPDF4LLM and rename it to old-style filename.

        返回：
            image_path:
                重命名后的图片路径，例如：
                data/images/{doc_hash}/d0af5bfe_2_1.png

            original_filename:
                重命名前的原始文件名，例如：
                2024.acl-long.93.pdf-0002-00.png

        旧逻辑要求最终保存的图片文件名是：
            {image_id}.png
        """

        if not image_dir.exists():
            return None, None

        image_files = sorted(
            list(image_dir.glob("*.png"))
            + list(image_dir.glob("*.jpg"))
            + list(image_dir.glob("*.jpeg"))
            + list(image_dir.glob("*.webp"))
        )

        matched_file: Optional[Path] = None

        for image_path in image_files:
            # 跳过已经被我们重命名成旧格式的图片
            # 例如 d0af5bfe_2_1.png 不应该再参与匹配
            if image_path.stem.startswith(f"{image_id.split('_')[0]}_"):
                continue

            # 只匹配当前 PDF 由 PyMuPDF4LLM 生成的原始图片
            # 例如 2024.acl-long.93.pdf-0002-00.png
            if not image_path.name.startswith(source_pdf_name):
                continue

            nums = [int(x) for x in re.findall(r"\d+", image_path.stem)]

            # PyMuPDF4LLM 常见命名：
            # 2024.acl-long.93.pdf-0002-00.png
            # 最后两个数字通常是：
            #   page_number = 2
            #   zero_based_image_index = 0
            if len(nums) >= 2:
                if nums[-2] == page_number and nums[-1] == zero_based_image_index:
                    matched_file = image_path
                    break

        if matched_file is None:
            return None, None

        original_filename = matched_file.name
        target_path = matched_file.with_name(f"{image_id}{matched_file.suffix.lower()}")

        if matched_file == target_path:
            return matched_file, original_filename

        try:
            if target_path.exists():
                target_path.unlink()

            matched_file.rename(target_path)

            return target_path, original_filename

        except Exception as e:
            logger.warning(
                f"Failed to rename image {matched_file} -> {target_path}: {e}"
            )

            # 如果重命名失败，至少返回原始图片路径和原始文件名
            return matched_file, original_filename
        
    def _replace_one_image_reference_in_page_text(
        self,
        page_text: str,
        token: str,
        original_filename: Optional[str] = None,
    ) -> str:
        """Replace one image reference in a page text with [IMAGE: image_id].

        替换优先级：
        1. 精确替换包含 original_filename 的 Markdown 图片链接；
        2. 如果精确替换失败，替换当前页第一个 Markdown 图片链接；
        3. 如果没有 Markdown 图片链接，替换 PyMuPDF4LLM 的 omitted marker；
        4. 如果都找不到，追加到当前页末尾。
        """

        modified_text = page_text

        # ------------------------------------------------------------
        # 1. 优先精确替换包含 original_filename 的 Markdown 图片链接
        # 例如：
        # ![](data/images/.../2024.acl-long.93.pdf-0002-00.png)
        # ------------------------------------------------------------
        if original_filename:
            exact_markdown_image_pattern = re.compile(
                r"!\[[^\]]*\]\([^\)]*"
                + re.escape(original_filename)
                + r"[^\)]*\)"
            )

            modified_text, count = exact_markdown_image_pattern.subn(
                token,
                modified_text,
                count=1,
            )

            if count > 0:
                return modified_text

        # ------------------------------------------------------------
        # 2. 如果精确匹配失败，替换当前页第一个剩余 Markdown 图片链接
        # 这可以兼容 original_filename 没拿到或路径格式变化的情况
        # ------------------------------------------------------------
        generic_markdown_image_pattern = re.compile(
            r"!\[[^\]]*\]\([^\)]*\.(?:png|jpg|jpeg|webp)[^\)]*\)",
            flags=re.IGNORECASE,
        )

        modified_text, count = generic_markdown_image_pattern.subn(
            token,
            modified_text,
            count=1,
        )

        if count > 0:
            return modified_text

        # ------------------------------------------------------------
        # 3. 替换 PyMuPDF4LLM 的 omitted marker
        # 例如：
        # **==> picture [455 x 336] intentionally omitted <==**
        # ------------------------------------------------------------
        omitted_picture_pattern = re.compile(
            r"\*\*==>\s*picture\s*\[\d+\s*x\s*\d+\]\s*intentionally omitted\s*<==\*\*",
            flags=re.IGNORECASE,
        )

        modified_text, count = omitted_picture_pattern.subn(
            token,
            modified_text,
            count=1,
        )

        if count > 0:
            return modified_text

        # ------------------------------------------------------------
        # 4. 最后保底：追加到当前页末尾
        # ------------------------------------------------------------
        if modified_text:
            return modified_text.rstrip() + "\n\n" + token

        return token


    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file content.
        # 计算PDF内容的SHA256哈希
        
        Args:
            file_path: Path to file.
            
        Returns:
            Hex string of SHA256 hash.
        """
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def _fix_hyphenated_line_breaks(self, text: str) -> str:
        """Fix PDF hyphenated line breaks.

        示例：
            Em-
            pirical -> Empirical

            contribut-
            ing -> contributing
        """

        if not text:
            return ""

        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 处理跨行 / 跨页断词，中间允许有空行
        text = re.sub(
            r"([A-Za-z])-\s*(?:\n\s*)+([a-z])",
            r"\1\2",
            text,
        )

        return text

    def _clean_pdf_page_noise(self, text: str) -> str:
        """Remove common PDF page-level noise.

        清理内容：
        1. 单独一行的页码；
        2. ACL / Anthology 页脚里的 Proceedings 行；
        3. 页码范围、会议日期、版权页脚；
        4. PyMuPDF4LLM 可能残留的多余空行。

        注意：
        这个函数会尽量避免误删 References 中的正常引用，
        例如 "- Alberti ... In Proceedings of the 57th Annual Meeting ..."
        """

        if not text:
            return ""

        text = text.replace("\r\n", "\n").replace("\r", "\n")

        lines = text.splitlines()
        cleaned_lines = []

        for idx, line in enumerate(lines):
            raw = line
            s = line.strip()

            if not s:
                cleaned_lines.append("")
                continue

            # ------------------------------------------------------------
            # 1. 删除单独一行的页码
            # 例如：
            # 307
            # 308
            # ------------------------------------------------------------
            if re.fullmatch(r"\d{1,4}", s):
                continue

            # ------------------------------------------------------------
            # 2. 删除 ACL / Anthology 页脚 Proceedings 行
            #
            # 只删除“行首就是 Proceedings of the ...”的页脚行，
            # 避免误删 References 中的：
            # "- xxx. In Proceedings of the 57th Annual Meeting ..."
            #
            # 可删除示例：
            # _Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics_
            # Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics
            # ------------------------------------------------------------
            if re.match(
                r"^_?\s*Proceedings of the .*?(Annual Meeting|Conference|Workshop)",
                s,
                flags=re.IGNORECASE,
            ) and re.search(
                r"Association for Computational Linguistics",
                s,
                flags=re.IGNORECASE,
            ):
                continue

            # ------------------------------------------------------------
            # 3. 删除 ACL 页脚版权行
            #
            # 可删除示例：
            # ©2024 Association for Computational Linguistics
            # © 2024 Association for Computational Linguistics
            # ------------------------------------------------------------
            if re.search(r"©\s*\d{4}", s) and re.search(
                r"Association for Computational Linguistics",
                s,
                flags=re.IGNORECASE,
            ):
                continue

            # ------------------------------------------------------------
            # 4. 删除页码范围 + 日期信息的页脚
            #
            # 可删除示例：
            # pages 307–317 August 11-16, 2024
            # pages 307-317, Bangkok, Thailand, August 11-16, 2024
            #
            # 这里要求行里有 pages/page + 页码范围 + 年份，
            # 避免误删普通正文。
            # ------------------------------------------------------------
            if re.search(
                r"\bpages?\s+\d+\s*[–-]\s*\d+.*\b(19\d{2}|20\d{2})\b",
                s,
                flags=re.IGNORECASE,
            ):
                continue

            # ------------------------------------------------------------
            # 5. 删除 ACL Anthology URL 页脚
            # 只删单独一行的 anthology 链接。
            # ------------------------------------------------------------
            if re.fullmatch(
                r"https?://aclanthology\.org/[^\s]+",
                s,
                flags=re.IGNORECASE,
            ):
                continue

            # ------------------------------------------------------------
            # 6. 删除常见“整行版权声明”
            # 注意：要求行里同时有 copyright / licensed / creative commons
            # 和 ACL 相关关键词，避免误删正文。
            # ------------------------------------------------------------
            if re.search(
                r"\b(copyright|licensed|creative commons)\b",
                s,
                flags=re.IGNORECASE,
            ) and re.search(
                r"\b(ACL|Association for Computational Linguistics|Anthology)\b",
                s,
                flags=re.IGNORECASE,
            ):
                continue

            cleaned_lines.append(raw)

        cleaned = "\n".join(cleaned_lines)

        # 压缩多余空行
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)


        return cleaned.strip()

    def _extract_title(self, text: str) -> Optional[str]:
        """Extract title from first Markdown heading or first non-empty line.
        从PDF文本中提取标题
        
        Args:
            text: Markdown text content.
            
        Returns:
            Title string if found, None otherwise.
        """
        lines = text.split('\n')
        
        # First try to find a markdown heading
        for line in lines[:20]:  # Check first 20 lines
            line = line.strip()
            if line.startswith('# '):
                return line[2:].strip()
        
        # Fallback: use first non-empty line as title
        for line in lines[:10]:
            line = line.strip()
            if line and len(line) > 0:
                return line
        
        return None
    
    
    
    def _extract_and_process_images(
        self,
        pdf_path: Path,
        text_content: str,
        doc_hash: str
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Extract images from PDF and insert placeholders.
        从PDF中提取图片，保存到磁盘，并在文本中插入占位符。
        
        Uses PyMuPDF to extract images, save them to disk, and insert
        placeholders in the text content.
        
        Args:
            pdf_path: Path to PDF file.
            text_content: Extracted text content.
            doc_hash: Document hash for image directory.
            
        Returns:
            Tuple of (modified_text, images_metadata_list)
        """
        if not self.extract_images:
            logger.debug(f"Image extraction disabled for {pdf_path}")
            return text_content, []
        
        if not PYMUPDF_AVAILABLE:
            logger.warning(f"PyMuPDF not available, skipping image extraction for {pdf_path}")
            return text_content, []
        
        images_metadata = []
        modified_text = text_content
        
        try:
            # Create image storage directory
            image_dir = self.image_storage_dir / doc_hash
            image_dir.mkdir(parents=True, exist_ok=True)
            
            # Open PDF with PyMuPDF
            doc = fitz.open(pdf_path)
            
            # Track text offset for placeholder insertion
            text_offset = 0
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images(full=True)
                
                for img_index, img_info in enumerate(image_list):
                    try:
                        # Extract image
                        xref = img_info[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        
                        # Generate image ID and filename
                        image_id = self._generate_image_id(doc_hash, page_num + 1, img_index + 1)
                        image_filename = f"{image_id}.{image_ext}"
                        image_path = image_dir / image_filename
                        
                        # Save image
                        with open(image_path, "wb") as img_file:
                            img_file.write(image_bytes)
                        
                        # Get image dimensions
                        try:
                            img = Image.open(io.BytesIO(image_bytes))
                            width, height = img.size
                        except Exception:
                            width, height = 0, 0
                        
                        # Create placeholder
                        placeholder = f"[IMAGE: {image_id}]"
                        
                        # Insert placeholder at end of current page's content
                        # (simplified - in production, you'd parse page boundaries)
                        insert_position = len(modified_text)
                        modified_text += f"\n{placeholder}\n"
                        
                        # Convert path to be relative to project root or absolute
                        try:
                            relative_path = image_path.relative_to(Path.cwd())
                        except ValueError:
                            # If not in cwd, use absolute path
                            relative_path = image_path.absolute()
                        
                        # Record metadata
                        image_metadata = {
                            "id": image_id,
                            "path": str(relative_path),
                            "page": page_num + 1,
                            "text_offset": insert_position + 1,  # +1 for newline 图片在纯文本流中的“插入点”
                            "text_length": len(placeholder), # 占位符的长度
                            "position": {
                                "width": width,
                                "height": height,
                                "page": page_num + 1,
                                "index": img_index # 图片在当前页面的顺序号。
                            }
                        }
                        images_metadata.append(image_metadata)
                        
                        logger.debug(f"Extracted image {image_id} from page {page_num + 1}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract image {img_index} from page {page_num + 1}: {e}")
                        continue
            
            doc.close()
            
            if images_metadata:
                logger.info(f"Extracted {len(images_metadata)} images from {pdf_path}")
            else:
                logger.debug(f"No images found in {pdf_path}")
            
            return modified_text, images_metadata
            
        except Exception as e:
            logger.warning(f"Image extraction failed for {pdf_path}: {e}")
            # Graceful degradation: return original text without images
            return text_content, []
    
    @staticmethod
    def _generate_image_id(doc_hash: str, page: int, sequence: int) -> str:
        """Generate unique image ID.
        生成唯一的图片ID。截取文档哈希前8位 + 页码 + 序号
        
        Args:
            doc_hash: Document hash.
            page: Page number (0-based).
            sequence: Image sequence on page (0-based).
            
        Returns:
            Unique image ID string.
        """
        return f"{doc_hash[:8]}_{page}_{sequence}"
