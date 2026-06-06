from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.libs.evaluator.base_evaluator import BaseEvaluator


class CustomEvaluator(BaseEvaluator):
    """Custom evaluator for lightweight metrics (hit_rate, mrr, hit@k, recall@k)."""

    SUPPORTED_METRICS = {
        "hit_rate",
        "mrr",
        "hit@1",
        "hit@5",
        "recall@5",
        "recall@10",
    }

    _ID_FIELDS = ("id", "chunk_id", "document_id", "doc_id")

    def __init__(
        self,
        settings: Any = None,
        metrics: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> None:
        self.settings = settings
        self.kwargs = kwargs

        if metrics is None:
            metrics = self._metrics_from_settings(settings)

        normalized = [str(metric).strip().lower() for metric in (metrics or [])]
        if not normalized:
            normalized = ["hit_rate", "mrr"]

        unsupported = [metric for metric in normalized if metric not in self.SUPPORTED_METRICS]
        if unsupported:
            raise ValueError(
                "Unsupported custom metrics: "
                f"{', '.join(unsupported)}. Supported: {', '.join(sorted(self.SUPPORTED_METRICS))}"
            )

        self.metrics = normalized

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

        retrieved_ids = self._extract_ids(retrieved_chunks, label="retrieved_chunks")
        ground_truth_ids = self._extract_ground_truth_ids(ground_truth)

        results: Dict[str, float] = {}

        # 原有指标（不改）
        if "hit_rate" in self.metrics:
            results["hit_rate"] = self._compute_hit_rate(retrieved_ids, ground_truth_ids)

        if "mrr" in self.metrics:
            results["mrr"] = self._compute_mrr(retrieved_ids, ground_truth_ids)

        # 新增指标（最小侵入）
        if "hit@1" in self.metrics:
            results["hit@1"] = self._compute_hit_k(retrieved_ids, ground_truth_ids, k=1)

        if "hit@5" in self.metrics:
            results["hit@5"] = self._compute_hit_k(retrieved_ids, ground_truth_ids, k=5)

        if "recall@5" in self.metrics:
            results["recall@5"] = self._compute_recall_k(retrieved_ids, ground_truth_ids, k=5)

        if "recall@10" in self.metrics:
            results["recall@10"] = self._compute_recall_k(retrieved_ids, ground_truth_ids, k=10)

        return results

    def _metrics_from_settings(self, settings: Any) -> List[str]:
        if settings is None:
            return []
        metrics = getattr(getattr(settings, "evaluation", None), "metrics", None)
        if metrics is None:
            return []
        return [str(metric) for metric in metrics]

    def _extract_ground_truth_ids(self, ground_truth: Optional[Any]) -> List[str]:
        if ground_truth is None:
            return []
        if isinstance(ground_truth, str):
            return [ground_truth]
        if isinstance(ground_truth, dict):
            if "ids" in ground_truth and isinstance(ground_truth["ids"], list):
                return self._extract_ids(ground_truth["ids"], label="ground_truth.ids")
            return self._extract_ids([ground_truth], label="ground_truth")
        if isinstance(ground_truth, list):
            return self._extract_ids(ground_truth, label="ground_truth")

        raise ValueError(
            f"Unsupported ground_truth type: {type(ground_truth).__name__}. "
            "Expected str, dict, list, or None."
        )

    def _extract_ids(self, items: Iterable[Any], label: str) -> List[str]:
        ids: List[str] = []
        for index, item in enumerate(items):
            if isinstance(item, str):
                ids.append(item)
                continue

            if isinstance(item, dict):
                for field in self._ID_FIELDS:
                    if field in item:
                        ids.append(str(item[field]))
                        break
                else:
                    raise ValueError(
                        f"Missing id field in {label}[{index}]. "
                        f"Expected one of {', '.join(self._ID_FIELDS)}"
                    )
                continue

            if hasattr(item, "chunk_id"):
                ids.append(str(getattr(item, "chunk_id")))
                continue

            if hasattr(item, "id"):
                ids.append(str(getattr(item, "id")))
                continue

            raise ValueError(
                f"Unable to extract id from {label}[{index}] of type "
                f"{type(item).__name__}"
            )

        return ids

    # ===== 原有函数（不改） =====

    def _compute_hit_rate(self, retrieved_ids: Sequence[str], ground_truth_ids: Sequence[str]) -> float:
        if not ground_truth_ids:
            return 0.0
        return 1.0 if any(item in ground_truth_ids for item in retrieved_ids) else 0.0

    def _compute_mrr(self, retrieved_ids: Sequence[str], ground_truth_ids: Sequence[str]) -> float:
        if not ground_truth_ids:
            return 0.0
        for rank, item in enumerate(retrieved_ids, start=1):
            if item in ground_truth_ids:
                return 1.0 / rank
        return 0.0

    # ===== 新增函数（只加，不动原逻辑） =====

    def _compute_hit_k(
        self,
        retrieved_ids: Sequence[str],
        ground_truth_ids: Sequence[str],
        k: int,
    ) -> float:
        if not ground_truth_ids:
            return 0.0
        top_k = retrieved_ids[:k]
        return 1.0 if any(item in ground_truth_ids for item in top_k) else 0.0

    def _compute_recall_k(
        self,
        retrieved_ids: Sequence[str],
        ground_truth_ids: Sequence[str],
        k: int,
    ) -> float:
        if not ground_truth_ids:
            return 0.0
        top_k = retrieved_ids[:k]
        hits = sum(1 for item in ground_truth_ids if item in top_k)
        return hits / len(ground_truth_ids)

"""Custom evaluator implementation for lightweight metrics.

This evaluator computes simple, deterministic metrics such as hit rate and MRR.
It is designed for fast regression checks and sanity validation.
这个评估器目前支持两个经典的检索指标：
命中率
定义：只要检索结果列表中包含任意一个正确答案（Ground Truth），就算命中。
计算逻辑：二值判断。命中了就是 1.0，没命中就是 0.0。
用途：衡量系统“能不能找到”相关文档。
平均倒数排名
定义：第一个正确答案出现在检索结果的第几位。
计算逻辑：
如果正确答案在第 1 位，分数是 1/1 = 1.0。
如果正确答案在第 2 位，分数是 1/2 = 0.5。
如果正确答案在第 10 位，分数是 1/10 = 0.1。
如果没找到，分数是 0.0。
用途：衡量系统“找得准不准”，是否把最相关的内容排在了最前面。
“提取 ID -> 比对 ID”。因为它是轻量级的，所以它不看文本内容，只看文档 ID 是否匹配。


from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.libs.evaluator.base_evaluator import BaseEvaluator


class CustomEvaluator(BaseEvaluator):
    Custom evaluator for lightweight metrics (hit_rate, mrr).


    The evaluator expects retrieved chunks to contain an identifier field.
    Supported id fields: id, chunk_id, document_id, doc_id.
    

    SUPPORTED_METRICS = {"hit_rate", "mrr"}
    _ID_FIELDS = ("id", "chunk_id", "document_id", "doc_id")

    def __init__(
        self,
        settings: Any = None,
        metrics: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> None:
        # 配置读取：通过 settings 或 metrics 参数决定要计算哪些指标（默认两个都算）。校验：如果用户传了不支持的指标名称，直接报错。
        self.settings = settings
        self.kwargs = kwargs

        if metrics is None:
            metrics = self._metrics_from_settings(settings)

        normalized = [str(metric).strip().lower() for metric in (metrics or [])]
        if not normalized:
            normalized = ["hit_rate", "mrr"]

        unsupported = [metric for metric in normalized if metric not in self.SUPPORTED_METRICS]
        if unsupported:
            raise ValueError(
                "Unsupported custom metrics: "
                f"{', '.join(unsupported)}. Supported: {', '.join(sorted(self.SUPPORTED_METRICS))}"
            )

        self.metrics = normalized

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        Compute requested metrics for the given retrieval results.

        Args:
            query: The user query string.
            retrieved_chunks: Retrieved chunks or records.
            generated_answer: Optional generated answer (unused).
            ground_truth: Ground truth ids or structure.
            trace: Optional TraceContext (unused).
            **kwargs: Additional parameters (unused).

        Returns:
            Dictionary of metric name to float value.
        
        self.validate_query(query)
        self.validate_retrieved_chunks(retrieved_chunks)

        retrieved_ids = self._extract_ids(retrieved_chunks, label="retrieved_chunks")
        ground_truth_ids = self._extract_ground_truth_ids(ground_truth)

        results: Dict[str, float] = {}

        if "hit_rate" in self.metrics:
            results["hit_rate"] = self._compute_hit_rate(retrieved_ids, ground_truth_ids)
        if "mrr" in self.metrics:
            results["mrr"] = self._compute_mrr(retrieved_ids, ground_truth_ids)

        return results

    def _metrics_from_settings(self, settings: Any) -> List[str]:
        Extract metrics list from settings if available.专门负责从复杂的 settings 对象深处把 metrics 配置挖出来。
        if settings is None:
            return []
        metrics = getattr(getattr(settings, "evaluation", None), "metrics", None)
        if metrics is None:
            return []
        return [str(metric) for metric in metrics]

    def _extract_ground_truth_ids(self, ground_truth: Optional[Any]) -> List[str]:
        Extract ground truth ids from various input shapes.
        这是一个“标准答案解析器”。作用：因为标准答案（Ground Truth）的格式千奇百怪，这个函数负责把它们统一成 ID 列表。
        它只看整体结构。它不关心具体的 ID 是什么，只关心数据是以什么形式（容器）存在的。
        作用：无论输入多乱，它保证输出给下一个函数的永远是一个可迭代的列表
        if ground_truth is None:
            return []
        if isinstance(ground_truth, str):
            return [ground_truth]
        if isinstance(ground_truth, dict):
            if "ids" in ground_truth and isinstance(ground_truth["ids"], list):
                return self._extract_ids(ground_truth["ids"], label="ground_truth.ids")
            return self._extract_ids([ground_truth], label="ground_truth")
        if isinstance(ground_truth, list):
            return self._extract_ids(ground_truth, label="ground_truth")

        raise ValueError(
            f"Unsupported ground_truth type: {type(ground_truth).__name__}. "
            "Expected str, dict, list, or None."
        )

    def _extract_ids(self, items: Iterable[Any], label: str) -> List[str]:
        Extract ids from a list of items.遍历一堆对象（无论是检索结果还是标准答案），把里面的 ID 抠出来。
        它只看具体元素。它接收上一步传来的列表，遍历每一个元素，把 ID 抠出来
        ids: List[str] = []
        for index, item in enumerate(items):
            if isinstance(item, str):  # 如果是字符串：直接拿走
                ids.append(item)
                continue
            if isinstance(item, dict):  # 如果是字典：按预定义的字段名（id, doc_id 等）去匹配。
                for field in self._ID_FIELDS:
                    if field in item:
                        ids.append(str(item[field]))
                        break
                else:
                    raise ValueError(
                        f"Missing id field in {label}[{index}]. "
                        f"Expected one of {', '.join(self._ID_FIELDS)}"
                    )
                continue
            if hasattr(item, "id"):  # 如果是对象：去读 .id 属性。
                ids.append(str(getattr(item, "id")))
                continue

            raise ValueError(
                f"Unable to extract id from {label}[{index}] of type "
                f"{type(item).__name__}"
            )

        return ids

    def _compute_hit_rate(self, retrieved_ids: Sequence[str], ground_truth_ids: Sequence[str]) -> float:
        Compute hit rate (binary).计算命中率
        if not ground_truth_ids:
            return 0.0
        return 1.0 if any(item in ground_truth_ids for item in retrieved_ids) else 0.0

    def _compute_mrr(self, retrieved_ids: Sequence[str], ground_truth_ids: Sequence[str]) -> float:
        Compute Mean Reciprocal Rank (MRR).计算平均倒数排名。
        if not ground_truth_ids:
            return 0.0
        for rank, item in enumerate(retrieved_ids, start=1):
            if item in ground_truth_ids:
                return 1.0 / rank
        return 0.0
"""