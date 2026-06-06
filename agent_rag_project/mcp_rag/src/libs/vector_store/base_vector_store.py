"""Abstract base class for VectorStore providers.

This module defines the pluggable interface for VectorStore providers,
enabling seamless switching between different backends (Chroma, Qdrant, Milvus, etc.)
through configuration-driven instantiation.
定义了所有向量数据库必须遵守的统一标准。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseVectorStore(ABC):
    """Abstract base class for VectorStore providers.
    
    All VectorStore implementations must inherit from this class and implement
    the upsert() and query() methods. This ensures consistent interface across
    different providers (Chroma, Qdrant, Milvus, etc.).
    
    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    - Idempotent: upsert() operations should be safely repeatable.
    抽象基类：制定一套“强制性的行业标准”，确保无论你以后使用 Chroma、Milvus 还是任何其他数据库，它们对外提供的接口（方法名、参数、返回值）都必须保持一致。
    """
    
    @abstractmethod
    def upsert(
        self,
        records: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Insert or update records in the vector store.
        
        Args:
            records: List of records to upsert. Each record is a dict with:
                - 'id': Unique identifier (str)
                - 'vector': Embedding vector (List[float])
                - 'metadata': Optional metadata dict (source, chunk_index, etc.)
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters.
        
        Raises:
            ValueError: If records list is empty or contains invalid entries.
            RuntimeError: If the vector store operation fails.
        
        Example:
            >>> records = [
            ...     {
            ...         'id': 'doc1_chunk0',
            ...         'vector': [0.1, 0.2, ..., 0.5],
            ...         'metadata': {'source': 'doc1.pdf', 'page': 1}
            ...     }
            ... ]
            >>> vector_store.upsert(records)
        
        Notes:
            - This operation should be idempotent: upserting the same record
              multiple times should produce the same final state.
            - Implementations should handle batch operations efficiently.

            作用：这是数据入库的唯一通道。
            标准要求：子类必须接受一个 records 列表。列表里的每一个元素（Dict）都必须包含 'id'（唯一标识）、'vector'（向量数据）和 'metadata'（元数据）。
            设计哲学:幂等性。意思是如果你用同一个 ID 上传两次数据，结果应该是一样的（通常是覆盖更新），这保证了数据的稳定性。
        """
        pass
    
    @abstractmethod
    def query(
        self,
        vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Query the vector store for similar vectors.
        
        Args:
            vector: Query vector (embedding) to search for.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters (e.g., {'source': 'doc1.pdf'}).
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters.
        
        Returns:
            List of matching records, sorted by similarity (descending).
            Each record is a dict with:
                - 'id': Record identifier
                - 'score': Similarity score (higher = more similar)
                - 'metadata': Associated metadata
                - 'vector': Optional, the stored vector (provider-dependent)
        
        Raises:
            ValueError: If vector is empty or top_k is invalid.
            RuntimeError: If the vector store query fails.
        
        Example:
            >>> query_vector = [0.1, 0.2, ..., 0.5]
            >>> results = vector_store.query(query_vector, top_k=5)
            >>> for result in results:
            ...     print(f"ID: {result['id']}, Score: {result['score']}")
        作用：这是根据语义搜索数据的通道。
        标准要求：输入一个 vector(用户问题的向量)，返回最相似的 top_k 条结果。
        返回格式：必须返回包含 'id'、'score'（相似度分数）、'metadata' 的列表。
        """
        pass

    # 内置安检：通用的数据校验员
    
    def validate_records(self, records: List[Dict[str, Any]]) -> None:
        """Validate records before upsert.
        
        Args:
            records: List of records to validate.
        
        Raises:
            ValueError: If records list is empty or contains invalid entries.
            它会在数据写入前自动检查：列表是否为空？每条数据是不是字典？有没有 ID?向量是不是列表格式?
            如果不符合规范，直接抛出 ValueError。这意味着所有继承它的子类(如 ChromaStore)天然拥有了这套“安检系统”，不需要自己重复写。
        
        """
        if not records:
            raise ValueError("Records list cannot be empty")
        
        for i, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Record at index {i} is not a dict (type: {type(record).__name__})"
                )
            
            # Validate required fields
            if 'id' not in record:
                raise ValueError(f"Record at index {i} is missing required field: 'id'")
            if 'vector' not in record:
                raise ValueError(f"Record at index {i} is missing required field: 'vector'")
            
            # Validate vector format
            vector = record['vector']
            if not isinstance(vector, (list, tuple)):
                raise ValueError(
                    f"Record at index {i} has invalid vector type: {type(vector).__name__}. "
                    "Expected list or tuple of floats."
                )
            
            if not vector:
                raise ValueError(f"Record at index {i} has empty vector")
    
    def validate_query_vector(self, vector: List[float], top_k: int) -> None:
        """Validate query parameters.
        
        Args:
            vector: Query vector to validate.
            top_k: Number of results to validate.
        
        Raises:
            ValueError: If parameters are invalid.
            检查搜索请求是否合法(向量不能为空,top_k 必须是正整数)
        """
        if not isinstance(vector, (list, tuple)):
            raise ValueError(
                f"Query vector must be a list or tuple, got {type(vector).__name__}"
            )
        
        if not vector:
            raise ValueError("Query vector cannot be empty")
        
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
    
    # 以下为可选功能

    def delete(
        self,
        ids: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Delete records from the vector store by IDs.
        
        Args:
            ids: List of record IDs to delete.
            trace: Optional TraceContext for observability.
            **kwargs: Provider-specific parameters.
        
        Raises:
            ValueError: If ids list is empty.
            RuntimeError: If the delete operation fails.
            NotImplementedError: If the provider doesn't support deletion.
        
        Notes:
            This is an optional operation. Providers that don't support
            deletion should raise NotImplementedError with a clear message.
        删除
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement delete() method. "
            "This operation is optional and provider-dependent."
        )
    
    def clear(
        self,
        collection_name: Optional[str] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Clear all records from the vector store or a specific collection.
        
        Args:
            collection_name: Optional collection name to clear. If None, clears default collection.
            trace: Optional TraceContext for observability.
            **kwargs: Provider-specific parameters.
        
        Raises:
            RuntimeError: If the clear operation fails.
            NotImplementedError: If the provider doesn't support clearing.
        
        Notes:
            This is primarily for testing and development. Use with caution in production.
        清空(测试时用)
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement clear() method. "
            "This operation is optional and primarily for testing."
        )
    
    def get_by_ids(
        self,
        ids: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Retrieve records by their IDs.
        
        This method is used by SparseRetriever to fetch text and metadata
        for chunks that were matched by BM25 search (which only returns IDs and scores).
        
        Args:
            ids: List of record IDs to retrieve.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters.
        
        Returns:
            List of records in the same order as input ids.
            Each record is a dict with:
                - 'id': Record identifier
                - 'text': The stored text content
                - 'metadata': Associated metadata
            If an ID is not found, an empty dict is returned for that position.
        
        Raises:
            ValueError: If ids list is empty.
            RuntimeError: If the retrieval operation fails.
            NotImplementedError: If the provider doesn't support this operation.
        
        Example:
            >>> ids = ["chunk_001", "chunk_002", "chunk_003"]
            >>> records = vector_store.get_by_ids(ids)
            >>> for record in records:
            ...     print(f"ID: {record['id']}, Text: {record['text'][:50]}...")
        
        Notes:
            This operation is essential for hybrid search where BM25 returns
            chunk IDs that need to be enriched with text and metadata from
            the vector store.
        (按 ID 获取)：这个比较特殊，主要用于混合检索（Hybrid Search）。
        场景：当你用 BM25（关键词匹配）搜到一堆 ID 后，你需要通过这个接口去数据库里把这些 ID 对应的原文捞出来。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_by_ids() method. "
            "This operation is required for SparseRetriever support."
        )
