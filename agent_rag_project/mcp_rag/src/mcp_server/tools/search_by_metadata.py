"""MCP Tool: search_by_metadata

Search the knowledge base with Agent/Harness-friendly metadata constraints.
This extends query_knowledge_hub with filters such as has_table, has_image,
source_ref/doc_id, source_path, section_title, exclude_references, and exclude_appendix.

Usage via MCP:
    Tool name: search_by_metadata
    Input schema:
        - query (string, required): Search query
        - filters (object, optional): Metadata or structural filters
        - top_k (integer, optional): Number of results
        - collection (string, optional): Collection name
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from mcp import types

from src.core.response.response_builder import MCPToolResponse, ResponseBuilder
from src.core.settings import Settings, load_settings, resolve_path
from src.core.trace import TraceCollector, TraceContext
from src.core.types import RetrievalResult

logger = logging.getLogger(__name__)


TOOL_NAME = "search_by_metadata"
TOOL_DESCRIPTION = """Search the knowledge base with metadata/structure filters.

Use this when the Agent knows the query should focus on a document subset,
such as table chunks, image chunks, a specific document, or non-reference sections.
Supported filters include:
- doc_id / source_ref
- source_path
- title
- section_title
- doc_type
- has_table
- has_image
- exclude_references
- exclude_appendix
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query.",
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of final results to return.",
            "default": 5,
            "minimum": 1,
            "maximum": 20,
        },
        "collection": {
            "type": "string",
            "description": "Optional collection name.",
        },
        "filters": {
            "type": "object",
            "description": "Metadata/structure filters, e.g. {\"has_table\": true, \"exclude_references\": true}.",
            "additionalProperties": True,
        },
    },
    "required": ["query"],
}


class SearchByMetadataTool:
    """Filtered search tool for Agent/RAG Harness usage."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        response_builder: Optional[ResponseBuilder] = None,
    ) -> None:
        self._settings = settings
        self._embedding_client = None
        self._hybrid_search = None
        self._reranker = None
        self._response_builder = response_builder or ResponseBuilder()
        self._current_collection: Optional[str] = None

        self.default_top_k = 5
        self.max_top_k = 20
        self.default_collection = "paper"
        self.enable_rerank = True

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings()
        return self._settings

    def _collection_name(self, collection: Optional[str]) -> str:
        if collection:
            return collection
        try:
            return getattr(self.settings.vector_store, "collection_name", self.default_collection)
        except AttributeError:
            return self.default_collection

    def _ensure_initialized(self, collection: str) -> None:
        logger.info("Initializing filtered search components for collection: %s", collection)

        from src.core.query_engine.query_processor import QueryProcessor
        from src.core.query_engine.hybrid_search import create_hybrid_search
        from src.core.query_engine.dense_retriever import create_dense_retriever
        from src.core.query_engine.sparse_retriever import create_sparse_retriever
        from src.core.query_engine.reranker import create_core_reranker
        from src.ingestion.storage.bm25_indexer import BM25Indexer
        from src.libs.embedding.embedding_factory import EmbeddingFactory
        from src.libs.vector_store.vector_store_factory import VectorStoreFactory

        if self._embedding_client is None:
            self._embedding_client = EmbeddingFactory.create(self.settings)

        if self._reranker is None:
            self._reranker = create_core_reranker(settings=self.settings)

        vector_store = VectorStoreFactory.create(
            self.settings,
            collection_name=collection,
        )
        dense_retriever = create_dense_retriever(
            settings=self.settings,
            embedding_client=self._embedding_client,
            vector_store=vector_store,
        )

        bm25_indexer = BM25Indexer(index_dir=str(resolve_path(f"data/db/bm25/{collection}")))
        sparse_retriever = create_sparse_retriever(
            settings=self.settings,
            bm25_indexer=bm25_indexer,
            vector_store=vector_store,
        )
        sparse_retriever.default_collection = collection

        self._hybrid_search = create_hybrid_search(
            settings=self.settings,
            query_processor=QueryProcessor(),
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
        )
        self._current_collection = collection

    @staticmethod
    def _looks_like_table(text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        pipe_lines = [line for line in lines if line.count("|") >= 2]
        return len(pipe_lines) >= 2

    @staticmethod
    def _has_image(text: str, metadata: Dict[str, Any]) -> bool:
        if "[IMAGE:" in (text or ""):
            return True
        if metadata.get("image_refs"):
            return True
        if metadata.get("images"):
            return True
        return False

    @staticmethod
    def _is_reference_chunk(text: str, metadata: Dict[str, Any]) -> bool:
        title = str(metadata.get("section_title") or metadata.get("title") or "").lower()
        first = ""
        for line in (text or "").splitlines():
            if line.strip():
                first = line.strip().lower()
                break
        return (
            "references" in title
            or first.startswith("## **references")
            or first.startswith("## references")
            or first.startswith("# references")
        )

    @staticmethod
    def _is_appendix_chunk(text: str, metadata: Dict[str, Any]) -> bool:
        title = str(metadata.get("section_title") or metadata.get("title") or "").lower()
        first = ""
        for line in (text or "").splitlines():
            if line.strip():
                first = line.strip().lower()
                break
        return "appendix" in title or first.startswith("## **appendix") or first.startswith("## appendix")

    @staticmethod
    def _contains_casefold(value: Any, pattern: Any) -> bool:
        if pattern in (None, ""):
            return True
        return str(pattern).casefold() in str(value or "").casefold()

    def _matches_filters(self, result: RetrievalResult, filters: Dict[str, Any]) -> bool:
        metadata = result.metadata or {}
        text = result.text or ""

        for key, expected in (filters or {}).items():
            if expected in (None, ""):
                continue

            if key in {"doc_id", "source_ref"}:
                actual = metadata.get("source_ref") or metadata.get("doc_id") or result.chunk_id
                if str(expected) not in str(actual) and str(expected) not in result.chunk_id:
                    return False

            elif key == "source_path":
                actual = metadata.get("source_path") or metadata.get("source") or ""
                if not self._contains_casefold(actual, expected):
                    return False

            elif key in {"title", "section_title"}:
                actual = metadata.get(key) or metadata.get("title") or ""
                if not self._contains_casefold(actual, expected):
                    return False

            elif key == "has_table":
                actual = bool(metadata.get("has_table")) or self._looks_like_table(text)
                if bool(expected) != actual:
                    return False

            elif key == "has_image":
                actual = bool(metadata.get("has_image")) or self._has_image(text, metadata)
                if bool(expected) != actual:
                    return False

            elif key == "exclude_references":
                if bool(expected) and self._is_reference_chunk(text, metadata):
                    return False

            elif key == "exclude_appendix":
                if bool(expected) and self._is_appendix_chunk(text, metadata):
                    return False

            elif key == "tags":
                actual_tags = metadata.get("tags", "")
                if isinstance(expected, list):
                    if not any(self._contains_casefold(actual_tags, item) for item in expected):
                        return False
                else:
                    if not self._contains_casefold(actual_tags, expected):
                        return False

            else:
                # Generic metadata exact-ish match. For strings, allow substring matching.
                actual = metadata.get(key)
                if isinstance(actual, str) or isinstance(expected, str):
                    if not self._contains_casefold(actual, expected):
                        return False
                else:
                    if actual != expected:
                        return False

        return True

    def _post_filter_results(
        self,
        results: List[RetrievalResult],
        filters: Optional[Dict[str, Any]],
    ) -> List[RetrievalResult]:
        if not filters:
            return results
        return [r for r in results if self._matches_filters(r, filters)]

    def _search(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]],
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        if self._hybrid_search is None:
            raise RuntimeError("HybridSearch not initialized")

        # Retrieve more candidates first, because structural filters may remove some.
        initial_top_k = min(max(top_k * 4, top_k), 80)

        raw = self._hybrid_search.search(
            query=query,
            top_k=initial_top_k,
            filters=None,
            trace=trace,
            return_details=False,
        )
        results = raw if isinstance(raw, list) else raw.results
        filtered = self._post_filter_results(results, filters)

        # Rerank after filtering so the reranker only sees allowed evidence.
        if self.enable_rerank and filtered and self._reranker is not None and self._reranker.is_enabled:
            try:
                rerank_result = self._reranker.rerank(
                    query=query,
                    results=filtered,
                    top_k=top_k,
                    trace=trace,
                )
                return rerank_result.results
            except Exception as e:
                logger.warning("Filtered reranking failed, using filtered retrieval order: %s", e)

        return filtered[:top_k]

    async def execute(
        self,
        query: str,
        top_k: int = 5,
        collection: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> MCPToolResponse:
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        effective_top_k = min(max(int(top_k), 1), self.max_top_k)
        effective_collection = self._collection_name(collection)
        filters = filters or {}

        trace = TraceContext(trace_type="query")
        trace.metadata["query"] = query[:200]
        trace.metadata["top_k"] = effective_top_k
        trace.metadata["collection"] = effective_collection
        trace.metadata["source"] = "mcp"
        trace.metadata["tool"] = TOOL_NAME
        trace.metadata["filters"] = filters

        try:
            await asyncio.to_thread(self._ensure_initialized, effective_collection)
            results = await asyncio.to_thread(
                self._search,
                query,
                effective_top_k,
                filters,
                trace,
            )

            response = self._response_builder.build(
                results=results,
                query=query,
                collection=effective_collection,
            )
            response.metadata["filters"] = filters
            response.metadata["tool"] = TOOL_NAME

            trace.metadata["final_results"] = [
                {
                    "chunk_id": r.chunk_id,
                    "score": round(r.score, 4),
                    "source": r.metadata.get("source_path", r.metadata.get("source", "")),
                    "title": r.metadata.get("title", ""),
                }
                for r in results
            ]
            TraceCollector().collect(trace)
            return response

        except Exception as e:
            logger.exception("search_by_metadata failed: %s", e)
            TraceCollector().collect(trace)
            return self._build_error_response(query, effective_collection, filters, str(e))

    def _build_error_response(
        self,
        query: str,
        collection: str,
        filters: Dict[str, Any],
        error_message: str,
    ) -> MCPToolResponse:
        content = "## 查询失败\n\n"
        content += f"查询: **{query}**\n"
        content += f"集合: `{collection}`\n"
        content += f"过滤条件: `{filters}`\n\n"
        content += f"**错误信息:** {error_message}\n"
        return MCPToolResponse(
            content=content,
            citations=[],
            metadata={
                "query": query,
                "collection": collection,
                "filters": filters,
                "error": error_message,
            },
            is_empty=True,
        )


_tool_instance: Optional[SearchByMetadataTool] = None


def get_tool_instance(settings: Optional[Settings] = None) -> SearchByMetadataTool:
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = SearchByMetadataTool(settings=settings)
    return _tool_instance


async def search_by_metadata_handler(
    query: str,
    top_k: int = 5,
    collection: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> types.CallToolResult:
    tool = get_tool_instance()
    try:
        response = await tool.execute(
            query=query,
            top_k=top_k,
            collection=collection,
            filters=filters,
        )
        return types.CallToolResult(
            content=response.to_mcp_content(),
            structured_data = response.to_dict()["structuredContent"],
            isError=response.is_empty and "error" in response.metadata,
        )
    except ValueError as e:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"参数错误: {e}")],
            isError=True,
        )
    except Exception as e:
        logger.exception("search_by_metadata handler error: %s", e)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="内部错误: 查询处理失败")],
            isError=True,
        )


def register_tool(protocol_handler) -> None:
    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=search_by_metadata_handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
