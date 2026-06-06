"""Chunk refinement transform: rule-based cleaning + optional LLM enhancement."""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

from src.core.settings import Settings, resolve_path
from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.ingestion.transform.base_transform import BaseTransform
from src.libs.llm.llm_factory import LLMFactory
from src.libs.llm.base_llm import BaseLLM, Message
from src.observability.logger import get_logger

logger = get_logger(__name__)

# Default max parallel workers for LLM calls
DEFAULT_MAX_WORKERS = 5


class ChunkRefiner(BaseTransform):
    """Refines chunks through rule-based cleaning and optional LLM enhancement.
    
    Processing Pipeline:
        1. Rule-based refine: Remove noise (whitespace, headers/footers, HTML)
        2. (Optional) LLM refine: Intelligent content improvement
        3. On LLM failure: Gracefully fallback to rule-based result
    
    Configuration (via settings.yaml):
        - ingestion.chunk_refiner.use_llm: bool - Enable LLM enhancement 启用LLM增强
        - ingestion.chunk_refiner.prompt_path: str - Custom prompt file path 自定义提示文件路径
    
    Design Principles:
        - Graceful Degradation: LLM errors don't block ingestion
        - Atomic Processing: Each chunk processed independently
        - Observable: Records refined_by in metadata
    """
    
    def __init__(
        self,
        settings: Settings,
        llm: Optional[BaseLLM] = None,
        prompt_path: Optional[str] = None
    ):
        """Initialize ChunkRefiner.

        LLM 是否启用由 settings.ingestion.chunk_refiner.use_llm 控制。

        use_llm=False:
            不初始化 LLM，不调用 LLM，只走 rule-based refine。

        use_llm=True:
            先 rule-based refine，再尝试 LLM refine。
        """

        self.settings = settings
        self._llm = llm
        self._prompt_template: Optional[str] = None

        # 兼容 settings.ingestion.chunk_refiner 是 dict 或对象两种情况
        ingestion_config = getattr(settings, "ingestion", None)
        chunk_refiner_config = (
            getattr(ingestion_config, "chunk_refiner", {})
            if ingestion_config is not None
            else {}
        )

        if isinstance(chunk_refiner_config, dict):
            config_use_llm = chunk_refiner_config.get("use_llm", False)
            config_prompt_path = chunk_refiner_config.get("prompt_path", None)
        else:
            config_use_llm = getattr(chunk_refiner_config, "use_llm", False)
            config_prompt_path = getattr(chunk_refiner_config, "prompt_path", None)

        self.use_llm = bool(config_use_llm)

        self._prompt_path = (
            prompt_path
            or config_prompt_path
            or str(resolve_path("config/prompts/chunk_refinement.txt"))
        )

        logger.info(
            f"ChunkRefiner initialized: use_llm={self.use_llm}, "
            f"prompt_path={self._prompt_path}"
        )
        
    @property
    def llm(self) -> Optional[BaseLLM]:
        """Lazy-load LLM instance."""
        if self.use_llm and self._llm is None:
            try:
                self._llm = LLMFactory.create(self.settings)
                logger.info("LLM initialized for chunk refinement")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM: {e}. Falling back to rule-based only.")
                self.use_llm = False
        return self._llm
    
    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """Transform chunks through refinement pipeline.

        use_llm=False:
            只执行 rule-based 清洗。

        use_llm=True:
            先执行 rule-based 清洗，再尝试 LLM refine。
            如果 LLM 初始化失败，自动 fallback 到 rule-based。
        """

        if not chunks:
            return []

        if self.use_llm:
            llm = self.llm

            if llm:
                logger.info("ChunkRefiner running with LLM refinement enabled")
                return self._transform_parallel(chunks, trace)

            logger.warning(
                "ChunkRefiner use_llm=True, but LLM is unavailable. "
                "Falling back to rule-based refinement."
            )

        logger.info("ChunkRefiner running with rule-based refinement only")
        return self._transform_sequential(chunks, trace)
    
    def _refine_single_chunk(
        self, 
        chunk: Chunk, 
        trace: Optional[TraceContext] = None
    ) -> Tuple[Chunk, str, Optional[str]]:
        """Refine a single chunk. Thread-safe.
        单个文本块的完整处理流水线（针对_transform_parallel）
        Args:
            chunk: Chunk to refine
            trace: Optional trace context
            
        Returns:
            Tuple of (refined_chunk, refined_by, error_message)
        """
        try:
            # Step 1: Rule-based refinement 规则清洗：先无条件执行 _rule_based_refine
            rule_refined_text = self._rule_based_refine(chunk.text)
            
            # Step 2: LLM enhancement LLM 增强：如果 LLM 可用，调用 _llm_refine 对清洗后的文本进行润色
            if self.use_llm and self.llm:
                llm_refined_text = self._llm_refine(rule_refined_text, trace)
                
                if llm_refined_text:
                    refined_text = llm_refined_text
                    refined_by = "llm"
                else:
                    refined_text = rule_refined_text
                    refined_by = "rule"
            else: # 降级逻辑：如果 LLM 返回空或报错，直接使用规则清洗的结果。
                refined_text = rule_refined_text
                refined_by = "rule"
            # 构建新 Chunk：创建一个新的 Chunk 对象，更新元数据（metadata['refined_by'] = 'llm' 或 'rule'）
            refined_chunk = Chunk(
                id=chunk.id,
                text=refined_text,
                metadata={
                    **(chunk.metadata or {}),#把原元数据解包
                    'refined_by': refined_by
                },
                source_ref=chunk.source_ref # 父文档的 ID
            )
            return (refined_chunk, refined_by, None)
            
        except Exception as e:
            logger.error(f"Failed to refine chunk {chunk.id}: {e}")
            return (chunk, "error", str(e))
    
    def _transform_parallel(
        self, 
        chunks: List[Chunk], 
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """Process chunks in parallel using ThreadPoolExecutor.
        利用多线程并发处理文本块，最大化利用 LLM 的吞吐量"""
        max_workers = min(DEFAULT_MAX_WORKERS, len(chunks))
        refined_chunks = [None] * len(chunks)
        llm_enhanced_count = 0
        fallback_count = 0
        
        logger.debug(f"Processing {len(chunks)} chunks in parallel (max_workers={max_workers})")
        # 创建线程池（ThreadPoolExecutor），最大线程数通常为 5
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks 将所有块提交给线程池并发执行 _refine_single_chunk
            future_to_idx = {
                executor.submit(self._refine_single_chunk, chunk, trace): idx
                for idx, chunk in enumerate(chunks)
            }
            
            # Collect results 在结果回收时，统计有多少块是 LLM 处理的，多少块是回退（Fallback）处理的
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    refined_chunk, refined_by, error = future.result()
                    refined_chunks[idx] = refined_chunk
                    
                    if refined_by == "llm":
                        llm_enhanced_count += 1
                    elif refined_by == "rule" and error is None:
                        fallback_count += 1
                except Exception as e:
                    logger.error(f"Unexpected error in parallel refinement: {e}")
                    refined_chunks[idx] = chunks[idx]
        
        success_count = sum(1 for c in refined_chunks if c is not None)
        
        if trace:
            trace.record_stage("chunk_refiner", {
                "total_chunks": len(chunks),
                "success_count": success_count,
                "llm_enhanced_count": llm_enhanced_count,
                "fallback_count": fallback_count,
                "use_llm": self.use_llm,
                "parallel": True,
                "max_workers": max_workers
            })
        
        logger.info(
            f"Refined {success_count}/{len(chunks)} chunks "
            f"(LLM: {llm_enhanced_count}, fallback: {fallback_count})"
        )
        
        return refined_chunks
    
    def _transform_sequential(
        self, 
        chunks: List[Chunk], 
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """Process chunks sequentially (fallback when LLM disabled).单线程顺序处理。当 LLM 不可用时，作为备胎使用。"""
        refined_chunks = []
        success_count = 0
        llm_enhanced_count = 0
        fallback_count = 0
        # 逐个遍历文本块
        for chunk in chunks:
            try:
                # Step 1: Rule-based refinement (always performed) 只执行规则清洗（_rule_based_refine），跳过 LLM 步骤。
                rule_refined_text = self._rule_based_refine(chunk.text)
                
                # Step 2: Optional LLM enhancement
                if self.use_llm and self.llm:
                    llm_refined_text = self._llm_refine(rule_refined_text, trace)
                    
                    if llm_refined_text:
                        # LLM success
                        refined_text = llm_refined_text
                        refined_by = "llm"
                        llm_enhanced_count += 1
                    else:
                        # LLM failed, fallback to rule-based
                        refined_text = rule_refined_text
                        refined_by = "rule"
                        fallback_count += 1
                        if chunk.metadata:
                            chunk.metadata['refine_fallback_reason'] = "llm_failed"
                else:
                    # LLM disabled, use rule-based
                    refined_text = rule_refined_text
                    refined_by = "rule"
                
                # Create refined chunk
                refined_chunk = Chunk(
                    id=chunk.id,
                    text=refined_text,
                    metadata={
                        **(chunk.metadata or {}),
                        'refined_by': refined_by
                    },
                    source_ref=chunk.source_ref
                )
                refined_chunks.append(refined_chunk)
                success_count += 1
                
            except Exception as e:
                # Atomic failure: log and preserve original
                logger.error(f"Failed to refine chunk {chunk.id}: {e}")
                refined_chunks.append(chunk)
        
        # Record trace
        if trace:
            trace.record_stage("chunk_refiner", {
                "total_chunks": len(chunks),
                "success_count": success_count,
                "llm_enhanced_count": llm_enhanced_count,
                "fallback_count": fallback_count,
                "use_llm": self.use_llm,
                "parallel": False
            })
        
        logger.info(
            f"Refined {success_count}/{len(chunks)} chunks "
            f"(LLM: {llm_enhanced_count}, fallback: {fallback_count})"
        )
        
        return refined_chunks
    
    def _rule_based_refine(self, text: str) -> str:
        """Apply conservative rule-based text cleaning.

        目标：
            1. 保留 Markdown 结构；
            2. 保留图片占位符 [IMAGE: xxx]；
            3. 保留 Markdown 表格结构；
            4. 保留公式、代码块；
            5. 清理明显 PDF / HTML 提取噪声；
            6. 不做文档特定词表修复。

        不做：
            1. 不删除 Markdown 标题；
            2. 不改写正文；
            3. 不总结；
            4. 不调用 LLM；
            5. 不做 lowresource -> low-resource 这种词典修复。
        """

        if not text:
            return text

        if not text.strip():
            return ""

        # 1. 保护 Markdown 代码块，避免后续规则误伤代码内容
        code_blocks = []
        code_block_pattern = r"```[\s\S]*?```"

        def extract_code_block(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

        text = re.sub(code_block_pattern, extract_code_block, text)

        # 2. 删除明显的长分隔线页眉/页脚块
        # 例如：
        # ───────── Page 1 Footer ─────────
        text = re.sub(
            r"─{10,}.*?(?:Page \d+|Footer|Section \d+|©|Confidential).*?─{10,}",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # 删除残留的纯长分隔线
        text = re.sub(r"─{10,}", "", text)

        # 3. 删除 HTML 注释
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

        # 4. 先处理 <br>，不能直接删除
        # 原因：
        #   Original Trainset<br>Baseline
        # 如果直接删标签，会变成：
        #   Original TrainsetBaseline
        #
        # 用 " / " 可以保留单元格内部多个值之间的边界，
        # 同时不会破坏 Markdown 表格行结构。
        text = re.sub(r"<br\s*/?>", " / ", text, flags=re.IGNORECASE)

        # 5. 删除剩余 HTML 标签，但保留标签内部文本
        # 例如：
        #   <b>Hello</b> -> Hello
        text = re.sub(r"<[^>]+>", "", text)

        # 6. 处理常见 HTML 实体
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )

        # 7. 压缩行内多余空格和 tab
        # 注意：
        #   只处理空格和 tab，不处理换行，
        #   避免把 Markdown 表格、标题、图片块揉成一行。
        text = re.sub(r"[ \t]{2,}", " ", text)

        # 8. 压缩过多空行，最多保留一个空行
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 9. 去掉每行末尾空白
        # 注意：
        #   只 rstrip，不 lstrip，
        #   避免破坏 Markdown 缩进、列表、代码等结构。
        lines = text.split("\n")
        lines = [line.rstrip() for line in lines]
        text = "\n".join(lines)

        # 10. 还原代码块
        for i, code_block in enumerate(code_blocks):
            text = text.replace(f"__CODE_BLOCK_{i}__", code_block)

        # 11. 最终清理全文首尾空白
        return text.strip()
    
    def _llm_refine(
        self,
        text: str,
        trace: Optional[TraceContext] = None
    ) -> Optional[str]:
        """Apply LLM-based intelligent refinement.
        
        Args:
            text: Rule-refined text
            trace: Optional trace context
            
        Returns:
            LLM-refined text, or None if refinement failed
        """
        if not text or not text.strip():
            return text
        
        try:
            # Load prompt template 加载 Prompt：读取外部的提示词模板文件
            prompt_template = self._load_prompt()
            if not prompt_template:
                logger.warning("Prompt template not found, skipping LLM refinement")
                return None
            
            # Fill prompt 组装 Prompt：将待处理文本插入到模板的 {text} 占位符中。
            if '{text}' not in prompt_template:
                logger.error("Prompt template missing {text} placeholder")
                return None
            
            prompt = prompt_template.replace('{text}', text)
            
            # Call LLM with Message objects 调用模型：发送给 LLM 进行对话
            messages = [Message(role="user", content=prompt)]
            response = self.llm.chat(messages, trace=trace)
            
            # Extract text from ChatResponse 提取结果：解析模型返回的 content
            if isinstance(response, str):
                refined_text = response
            else:
                # response is ChatResponse object
                refined_text = response.content
            # 空值保护：如果模型返回空或报错，返回 None，触发上层的降级逻辑。
            if refined_text and refined_text.strip():  # .strip()去除首尾空格
                return refined_text.strip()
            else:
                logger.warning("LLM returned empty result")
                return None
                
        except Exception as e:
            logger.warning(f"LLM refinement failed: {e}")
            return None
    
    def _load_prompt(self) -> Optional[str]:
        """Load prompt template from file.
        
        Returns:
            Prompt template string, or None if file not found
        """
        if self._prompt_template is not None:
            return self._prompt_template
        
        try:
            prompt_path = Path(self._prompt_path)
            if not prompt_path.exists():
                logger.warning(f"Prompt file not found: {self._prompt_path}")
                return None
            
            self._prompt_template = prompt_path.read_text(encoding='utf-8')
            logger.debug(f"Loaded prompt template from {self._prompt_path}")
            return self._prompt_template
            
        except Exception as e:
            logger.error(f"Failed to load prompt template: {e}")
            return None
