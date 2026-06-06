"""MCP Tool: get_document_full_text

Locate a single document by doc_id or metadata/search conditions, then return
the full reconstructed text by concatenating all stored chunks in order.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mcp import types

from src.core.settings import Settings, load_settings
from src.mcp_server.tools.get_document_outline import (
    DocumentOutlineNotFoundError,
    GetDocumentOutlineTool,
)
from src.mcp_server.tools.list_documents import ListDocumentsTool
from src.mcp_server.tools.search_by_metadata import SearchByMetadataTool

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler

logger = logging.getLogger(__name__)


TOOL_NAME = "get_document_full_text"
TOOL_DESCRIPTION = """Return the full text of one document from the knowledge base.

Provide **doc_id** directly, or locate a document using **query** + **filters**
(same filter keys as search_by_metadata: doc_id, source_ref, source_path, title,
section_title, has_table, has_image, exclude_references, exclude_appendix, etc.),
or use **source_path** / **title** alone for metadata matching.

Concatenates all chunks for that document in chunk_index order. Use when the Agent
needs the entire document body, not just top-k retrieval hits.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "doc_id": {
            "type": "string",
            "description": (
                "Document ID / source_ref. If set, loads this document directly "
                "(other locators are ignored)."
            ),
        },
        "query": {
            "type": "string",
            "description": (
                "Optional search query used with filters to locate exactly one "
                "document when doc_id is omitted."
            ),
        },
        "filters": {
            "type": "object",
            "description": (
                "Metadata/structure filters (search_by_metadata semantics). "
                "Merged with source_path/title top-level args when provided."
            ),
            "additionalProperties": True,
        },
        "source_path": {
            "type": "string",
            "description": "Substring match on stored source_path/source (when doc_id omitted).",
        },
        "title": {
            "type": "string",
            "description": "Substring match on document title metadata (when doc_id omitted).",
        },
        "collection": {
            "type": "string",
            "description": "Optional ChromaDB collection name.",
        },
        "exclude_references": {
            "type": "boolean",
            "description": "If true, omit chunks detected as References section.",
            "default": False,
        },
        "exclude_appendix": {
            "type": "boolean",
            "description": "If true, omit chunks detected as Appendix section.",
            "default": False,
        },
        "max_chars": {
            "type": "integer",
            "description": "Maximum characters in returned full_text (truncates tail).",
            "default": 120000,
            "minimum": 1000,
            "maximum": 500000,
        },
        "search_top_k": {
            "type": "integer",
            "description": "When resolving via query+filters, retrieval candidate count.",
            "default": 20,
            "minimum": 1,
            "maximum": 50,
        },
    },
    "required": [],
}


@dataclass
class DocumentFullText:
    doc_id: str
    title: str
    source_path: Optional[str]
    full_text: str
    chunk_count: int
    chunks_included: int
    char_count: int
    truncated: bool
    collection: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class DocumentNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class AmbiguousDocumentError(Exception):
    def __init__(self, doc_ids: List[str]):
        ids = ", ".join(doc_ids[:10])
        suffix = f" ... +{len(doc_ids) - 10} more" if len(doc_ids) > 10 else ""
        super().__init__(
            f"Multiple documents matched the given conditions: {ids}{suffix}. "
            "Provide doc_id explicitly or narrow filters."
        )
        self.doc_ids = doc_ids


class GetDocumentFullTextTool:
    """Load and concatenate all chunks for one document."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings
        self._outline_tool = GetDocumentOutlineTool(settings=settings)
        self._list_tool = ListDocumentsTool(settings=settings)
        self._search_tool: Optional[SearchByMetadataTool] = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings()
        return self._settings

    def _collection_name(self, collection: Optional[str]) -> str:
        if collection:
            return collection
        try:
            return getattr(
                self.settings.vector_store,
                "collection_name",
                "paper",
            )
        except AttributeError:
            return "paper"

    def _get_search_tool(self) -> SearchByMetadataTool:
        if self._search_tool is None:
            self._search_tool = SearchByMetadataTool(settings=self.settings)
        return self._search_tool

    @staticmethod
    def _contains_casefold(value: Any, pattern: Any) -> bool:
        if pattern in (None, ""):
            return True
        return str(pattern).casefold() in str(value or "").casefold()

    @staticmethod
    def _doc_id_from_metadata(chunk_id: str, metadata: Dict[str, Any]) -> str:
        if metadata.get("source_ref"):
            return str(metadata["source_ref"])
        if metadata.get("doc_id"):
            return str(metadata["doc_id"])
        source_path = metadata.get("source_path") or metadata.get("source")
        if source_path:
            return "doc_" + Path(str(source_path)).stem
        parts = chunk_id.split("_")
        if len(parts) >= 3 and parts[-2].isdigit():
            return "_".join(parts[:-2])
        return chunk_id

    def _merge_filters(
        self,
        filters: Optional[Dict[str, Any]],
        source_path: Optional[str],
        title: Optional[str],
    ) -> Dict[str, Any]:
        merged: Dict[str, Any] = dict(filters or {})
        if source_path and "source_path" not in merged:
            merged["source_path"] = source_path
        if title and "title" not in merged:
            merged["title"] = title
        return merged

    def _resolve_doc_id_by_metadata(
        self,
        collection: str,
        source_path: Optional[str],
        title: Optional[str],
        filters: Dict[str, Any],
    ) -> str:
        # If filters already pin doc_id / source_ref, use that directly.
        for key in ("doc_id", "source_ref"):
            if filters.get(key):
                return str(filters[key])

        documents = self._list_tool.list_documents(collection=collection, limit=500)
        matched: List[str] = []
        for doc in documents:
            ok = True
            if source_path and not self._contains_casefold(doc.source_path, source_path):
                ok = False
            if title and not self._contains_casefold(doc.title, title):
                ok = False
            if filters.get("section_title"):
                meta_title = doc.metadata.get("section_title") or ""
                if not self._contains_casefold(meta_title, filters["section_title"]):
                    ok = False
            if ok:
                matched.append(doc.doc_id)

        matched = list(dict.fromkeys(matched))
        if not matched:
            raise DocumentNotFoundError(
                "No document matched source_path/title/filters in the collection."
            )
        if len(matched) > 1:
            raise AmbiguousDocumentError(matched)
        return matched[0]

    def _resolve_doc_id_by_search(
        self,
        query: str,
        collection: str,
        filters: Dict[str, Any],
        search_top_k: int,
    ) -> str:
        search_tool = self._get_search_tool()
        search_tool._ensure_initialized(collection)
        results = search_tool._search(
            query=query,
            top_k=min(max(search_top_k, 1), 50),
            filters=filters or None,
            trace=None,
        )
        if not results:
            raise DocumentNotFoundError(
                f"No retrieval hits for query={query!r} with the given filters."
            )

        doc_ids: List[str] = []
        for result in results:
            meta = result.metadata or {}
            doc_ids.append(self._doc_id_from_metadata(result.chunk_id, meta))

        unique = list(dict.fromkeys(doc_ids))
        if len(unique) == 1:
            return unique[0]
        raise AmbiguousDocumentError(unique)

    def resolve_doc_id(
        self,
        doc_id: Optional[str],
        query: Optional[str],
        filters: Optional[Dict[str, Any]],
        source_path: Optional[str],
        title: Optional[str],
        collection: Optional[str],
        search_top_k: int,
    ) -> str:
        if doc_id and doc_id.strip():
            return doc_id.strip()

        merged_filters = self._merge_filters(filters, source_path, title)
        collection_name = self._collection_name(collection)

        has_meta_locator = bool(
            source_path
            or title
            or merged_filters.get("doc_id")
            or merged_filters.get("source_ref")
            or merged_filters.get("source_path")
            or merged_filters.get("section_title")
        )

        if query and query.strip():
            return self._resolve_doc_id_by_search(
                query.strip(),
                collection_name,
                merged_filters,
                search_top_k,
            )

        if has_meta_locator:
            return self._resolve_doc_id_by_metadata(
                collection_name,
                source_path,
                title,
                merged_filters,
            )

        raise ValueError(
            "Provide doc_id, or query (optionally with filters), "
            "or source_path/title/filters to locate a document."
        )

    def get_document_full_text(
        self,
        doc_id: Optional[str] = None,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        source_path: Optional[str] = None,
        title: Optional[str] = None,
        collection: Optional[str] = None,
        exclude_references: bool = False,
        exclude_appendix: bool = False,
        max_chars: int = 120000,
        search_top_k: int = 20,
    ) -> DocumentFullText:
        effective_max = min(max(int(max_chars), 1000), 500000)
        collection_name = self._collection_name(collection)

        resolved_doc_id = self.resolve_doc_id(
            doc_id=doc_id,
            query=query,
            filters=filters,
            source_path=source_path,
            title=title,
            collection=collection,
            search_top_k=search_top_k,
        )

        chunks = self._outline_tool._load_document_chunks(resolved_doc_id, collection)
        if not chunks:
            raise DocumentOutlineNotFoundError(resolved_doc_id, collection)

        chunks.sort(
            key=lambda c: (
                self._outline_tool._to_int(c.get("metadata", {}).get("chunk_index"), 10**9),
                c["id"],
            )
        )

        first_meta = chunks[0].get("metadata", {}) or {}
        doc_title = str(first_meta.get("title") or "").strip() or "Untitled Document"
        doc_source = first_meta.get("source_path") or first_meta.get("source")
        resolved_ref = str(
            first_meta.get("source_ref") or first_meta.get("doc_id") or resolved_doc_id
        )

        parts: List[str] = []
        included = 0
        for chunk in chunks:
            text = chunk.get("text", "") or ""
            metadata = chunk.get("metadata", {}) or {}
            if exclude_references and self._outline_tool._is_references_chunk(text, metadata):
                continue
            if exclude_appendix and self._outline_tool._is_appendix_chunk(text, metadata):
                continue
            if text.strip():
                parts.append(text.strip())
                included += 1

        full_text = "\n\n".join(parts)
        truncated = False
        if len(full_text) > effective_max:
            full_text = full_text[: effective_max - 20] + "\n\n…[truncated]"
            truncated = True

        return DocumentFullText(
            doc_id=resolved_ref,
            title=doc_title,
            source_path=str(doc_source) if doc_source else None,
            full_text=full_text,
            chunk_count=len(chunks),
            chunks_included=included,
            char_count=len(full_text),
            truncated=truncated,
            collection=collection_name,
            metadata={
                "requested_doc_id": doc_id,
                "resolved_via_query": bool(query and query.strip() and not doc_id),
                "filters": filters or {},
            },
        )

    def format_response(self, result: DocumentFullText) -> str:
        lines = [
            f"## Full Document Text: {result.title}",
            "",
            f"**Document ID:** `{result.doc_id}`",
        ]
        if result.source_path:
            lines.append(f"**Source:** {result.source_path}")
        lines.extend([
            f"**Collection:** `{result.collection}`",
            f"**Chunks (total / included):** {result.chunk_count} / {result.chunks_included}",
            f"**Characters returned:** {result.char_count}",
        ])
        if result.truncated:
            lines.append("**Note:** Output was truncated to max_chars.")

        lines.extend([
            "",
            "---",
            "",
            result.full_text,
        ])
        return "\n".join(lines)

    def format_error(self, error: Exception) -> str:
        if isinstance(error, (DocumentNotFoundError, DocumentOutlineNotFoundError)):
            return f"## Document Not Found\n\n{error}"
        if isinstance(error, AmbiguousDocumentError):
            return f"## Ambiguous Match\n\n{error}"
        if isinstance(error, ValueError):
            return f"## Invalid Request\n\n{error}"
        return f"## Error\n\nAn error occurred: {error}"

    def to_structured_content(self, result: DocumentFullText) -> Dict[str, Any]:
        return {
            "doc_id": result.doc_id,
            "title": result.title,
            "source_path": result.source_path,
            "collection": result.collection,
            "chunk_count": result.chunk_count,
            "chunks_included": result.chunks_included,
            "char_count": result.char_count,
            "truncated": result.truncated,
            "full_text": result.full_text,
            "text": result.full_text,
            "metadata": result.metadata,
        }

    async def execute(
        self,
        doc_id: Optional[str] = None,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        source_path: Optional[str] = None,
        title: Optional[str] = None,
        collection: Optional[str] = None,
        exclude_references: bool = False,
        exclude_appendix: bool = False,
        max_chars: int = 120000,
        search_top_k: int = 20,
    ) -> types.CallToolResult:
        logger.info(
            "Executing get_document_full_text (doc_id=%s, query=%s, collection=%s)",
            doc_id,
            (query or "")[:80],
            collection,
        )
        try:
            result = await asyncio.to_thread(
                self.get_document_full_text,
                doc_id,
                query,
                filters,
                source_path,
                title,
                collection,
                exclude_references,
                exclude_appendix,
                max_chars,
                search_top_k,
            )
            structured = self.to_structured_content(result)
            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=self.format_response(result)),
                ],
                structured_data=structured,
                isError=False,
            )
        except Exception as e:
            logger.exception("Error executing get_document_full_text")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_error(e))],
                isError=True,
            )


_tool_instance: Optional[GetDocumentFullTextTool] = None


def get_tool_instance(settings: Optional[Settings] = None) -> GetDocumentFullTextTool:
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = GetDocumentFullTextTool(settings=settings)
    return _tool_instance


async def get_document_full_text_handler(
    doc_id: Optional[str] = None,
    query: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    source_path: Optional[str] = None,
    title: Optional[str] = None,
    collection: Optional[str] = None,
    exclude_references: bool = False,
    exclude_appendix: bool = False,
    max_chars: int = 120000,
    search_top_k: int = 20,
) -> types.CallToolResult:
    tool = get_tool_instance()
    return await tool.execute(
        doc_id=doc_id,
        query=query,
        filters=filters,
        source_path=source_path,
        title=title,
        collection=collection,
        exclude_references=exclude_references,
        exclude_appendix=exclude_appendix,
        max_chars=max_chars,
        search_top_k=search_top_k,
    )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=get_document_full_text_handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
