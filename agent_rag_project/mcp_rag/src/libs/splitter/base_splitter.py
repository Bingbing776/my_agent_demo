"""Abstract base class for text splitters.

This module defines the pluggable interface for text splitter providers,
enabling seamless switching between different splitting strategies
(Recursive, Semantic, FixedLength, etc.) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseSplitter(ABC):
    """Abstract base class for text splitters.
    
    All splitter implementations must inherit from this class and implement
    the split_text() method. This ensures a consistent interface across
    different strategies.
    
    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """
    
    @abstractmethod
    def split_text(
        self,
        text: str, # 要非空
        trace: Optional[Any] = None, # 可选的TraceContext，用于可观察性（专为Stage F预留）
        **kwargs: Any, # 特定策略的参数（如块大小、重叠率等）
    ) -> List[str]: # 输出返回列表，顺序必须保持原始文本的顺序
        """Split input text into a list of chunks.
        将输入文本分割成多个文本块的核心方法（抽象）
        Args:
            text: Input text to split. Must be a non-empty string.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Strategy-specific parameters (chunk_size, overlap, etc.).
        
        Returns:
            A list of text chunks. Order must preserve the original text sequence.
        
        Raises:
            ValueError: If input text is invalid.
            RuntimeError: If the splitter fails unexpectedly.
        """
        pass
    
    def validate_text(self, text: str) -> None:
        """Validate input text.验证输入文本的有效性
        
        Args:
            text: Input text to validate.
        
        Raises:
            ValueError: If text is not a non-empty string.
        """
        if not isinstance(text, str):
            raise ValueError(f"Input text must be a string, got {type(text).__name__}")
        if not text.strip():
            raise ValueError("Input text cannot be empty or whitespace-only")
    
    def validate_chunks(self, chunks: List[str]) -> None:
        """Validate output chunks.验证分割结果的有效性
        
        Args:
            chunks: List of chunk strings to validate.
        
        Raises:
            ValueError: If chunks are empty or contain invalid entries.
        结构验证：确认输出是列表类型
        非空验证：确保结果列表不为空
        元素验证：检查每个块都是非空字符串
        索引提示：在验证失败时指出具体位置
        质量保证：确保分割结果可用
        """
        if not isinstance(chunks, list):
            raise ValueError("Chunks must be a list of strings")
        if not chunks:
            raise ValueError("Chunks list cannot be empty")
        for i, chunk in enumerate(chunks):
            if not isinstance(chunk, str):
                raise ValueError(
                    f"Chunk at index {i} is not a string (type: {type(chunk).__name__})"
                )
            if not chunk.strip():
                raise ValueError(
                    f"Chunk at index {i} is empty or whitespace-only"
                )