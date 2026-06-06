"""Abstract base class for Evaluator providers.

This module defines the pluggable interface for evaluation providers,
enabling seamless switching between different evaluation backends
through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseEvaluator(ABC):
    """Abstract base class for evaluation providers.

    All evaluator implementations must inherit from this class and implement
    the evaluate() method. This ensures a consistent interface across different
    evaluation backends.

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def evaluate(
        self,
        query: str,  # 用户问题
        retrieved_chunks: List[Any], # 系统检索到了哪些文档片段。
        generated_answer: Optional[str] = None, # 系统生成的回答（可选）
        ground_truth: Optional[Any] = None, # 标准答案（可选，用于计算准确率）
        trace: Optional[Any] = None,  # 链路追踪上下文（用于监控）
        **kwargs: Any,
    ) -> Dict[str, float]: # 返回一个字典 Dict[str, float]，键是指标名称（如 "precision", "recall"），值是分数（如 0.95）
        """Evaluate retrieval and generation quality.

        Args:
            query: The user query string.
            retrieved_chunks: Retrieved chunks or records to evaluate.
            generated_answer: Optional generated answer text.
            ground_truth: Optional ground truth data (ids or answers).
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters.

        Returns:
            Dictionary of metric names to float values.

        Raises:
            ValueError: If inputs are invalid.
            RuntimeError: If evaluation fails unexpectedly.
        """
        pass

    def validate_query(self, query: str) -> None:
        """Validate query string.确保查询是字符串且不为空

        Args:
            query: Query string to validate.

        Raises:
            ValueError: If query is invalid.
        """
        if not isinstance(query, str):
            raise ValueError(f"Query must be a string, got {type(query).__name__}")
        if not query.strip():
            raise ValueError("Query cannot be empty or whitespace-only")

    def validate_retrieved_chunks(self, retrieved_chunks: List[Any]) -> None:
        """Validate retrieved chunks structure. 确保检索结果是一个非空列表

        Args:
            retrieved_chunks: Retrieved chunks list to validate.

        Raises:
            ValueError: If retrieved_chunks is invalid.
        """
        if not isinstance(retrieved_chunks, list):
            raise ValueError("retrieved_chunks must be a list")
        if not retrieved_chunks:
            raise ValueError("retrieved_chunks cannot be empty")


class NoneEvaluator(BaseEvaluator):
    """No-op evaluator that returns empty metrics.这是一个空对象模式的实现，用于处理“评估被禁用”的情况。
    当配置文件里关闭了评估功能，或者用户不想进行评估时，系统不会报错，而是使用这个类。
    This implementation is used when evaluation is disabled.
    """

    def __init__(self, settings: Any = None, **kwargs: Any) -> None:
        self.settings = settings
        self.kwargs = kwargs

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        self.validate_query(query)
        self.validate_retrieved_chunks(retrieved_chunks)
        return {}