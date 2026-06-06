"""
Vector Store Module.

This package contains vector store abstractions and implementations:
- Base vector store class
- Vector store factory
- Implementations (Chroma, etc.)
将上述组件组装起来，对外暴露接口，并完成插件的自动注册。
"""

from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.vector_store.vector_store_factory import VectorStoreFactory

# Auto-register ChromaStore provider 注册ChromaStore通过vector_store_factory
try:
    from src.libs.vector_store.chroma_store import ChromaStore
    # import vector_store就进行下面的注册
    VectorStoreFactory.register_provider('chroma', ChromaStore)
except ImportError:
    # ChromaDB not installed, skip registration
    pass

# 这样用户可以直接导入用户可以直接导入：from vector_store import VectorStoreFactory, BaseVectorStore, ChromaStore
__all__ = [
    'BaseVectorStore',
    'VectorStoreFactory',
    'ChromaStore',
]
