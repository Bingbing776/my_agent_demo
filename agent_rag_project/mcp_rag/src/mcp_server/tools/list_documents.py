"""MCP Tool: list_documents

List documents inside a ChromaDB collection by grouping chunks by source_ref or source_path.
This is a collection-discovery tool for an Agent/RAG Harness layer.

Usage via MCP:
    Tool name: list_documents
    Input schema:
        - collection (string, optional): Collection name
        - limit (integer, optional): Max number of documents to return
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "list_documents"
TOOL_DESCRIPTION = """List documents in a knowledge base collection.

Groups stored chunks by parent document, returning doc_id/source_ref, title,
source_path, chunk_count, and basic document metadata.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "collection": {
            "type": "string",
            "description": "Optional ChromaDB collection name. Uses default collection if omitted.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of documents to return.",
            "default": 50,
            "minimum": 1,
            "maximum": 500,
        },
    },
    "required": [],
}


@dataclass
class ListDocumentsConfig:
    persist_directory: str = "./data/db/chroma"
    default_collection: str = "paper"


@dataclass
class DocumentInfo:
    doc_id: str
    title: str
    source_path: Optional[str] = None
    chunk_count: int = 0
    first_chunk_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ListDocumentsTool:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[ListDocumentsConfig] = None,
    ) -> None:
        self._settings = settings
        self._config = config
        self._chroma_client = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            from src.core.settings import load_settings
            self._settings = load_settings()
        return self._settings

    @property
    def config(self) -> ListDocumentsConfig:
        if self._config is None:
            try:
                persist_dir = getattr(
                    self.settings.vector_store,
                    "persist_directory",
                    "./data/db/chroma",
                )
                default_collection = getattr(
                    self.settings.vector_store,
                    "collection_name",
                    "paper",
                )
            except AttributeError:
                persist_dir = "./data/db/chroma"
                default_collection = "paper"

            self._config = ListDocumentsConfig(
                persist_directory=persist_dir,
                default_collection=default_collection,
            )
        return self._config

    def _get_chroma_client(self) -> Any:
        if self._chroma_client is not None:
            return self._chroma_client

        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            raise ImportError("chromadb package is required. Install it with: pip install chromadb")

        persist_path = Path(self.config.persist_directory).resolve()
        persist_path.mkdir(parents=True, exist_ok=True)
        self._chroma_client = chromadb.PersistentClient(
            path=str(persist_path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        return self._chroma_client

    def _get_collection(self, collection_name: Optional[str] = None) -> Any:
        client = self._get_chroma_client()
        name = collection_name or self.config.default_collection
        try:
            return client.get_collection(name=name)
        except Exception as e:
            raise ValueError(f"Collection '{name}' does not exist: {e}") from e

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _extract_title(metadata: Dict[str, Any], text: str, source_path: Optional[str]) -> str:
        if metadata.get("title"):
            return str(metadata["title"])

        for line in (text or "").splitlines()[:10]:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
            if line.startswith("## "):
                return line[3:].strip()

        if source_path:
            return Path(str(source_path)).stem.replace("_", " ").replace("-", " ").title()

        return "Untitled Document"

    @staticmethod
    def _doc_id_from_record(chunk_id: str, metadata: Dict[str, Any]) -> str:
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

    def list_documents(
        self,
        collection: Optional[str] = None,
        limit: int = 50,
    ) -> List[DocumentInfo]:
        limit = max(1, min(int(limit), 500))
        chroma_collection = self._get_collection(collection)

        results = chroma_collection.get(include=["metadatas", "documents"])
        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for i, chunk_id in enumerate(ids):
            metadata = metas[i] if i < len(metas) and metas[i] else {}
            text = docs[i] if i < len(docs) and docs[i] else ""
            doc_id = self._doc_id_from_record(chunk_id, metadata)
            groups.setdefault(doc_id, []).append({
                "id": chunk_id,
                "text": text,
                "metadata": metadata,
            })

        documents: List[DocumentInfo] = []
        for doc_id, chunks in groups.items():
            chunks.sort(
                key=lambda c: (
                    self._to_int(c.get("metadata", {}).get("chunk_index"), 10**9),
                    c["id"],
                )
            )
            first = chunks[0]
            metadata = first.get("metadata", {})
            source_path = metadata.get("source_path") or metadata.get("source")
            title = self._extract_title(metadata, first.get("text", ""), source_path)

            public_metadata = {
                k: v for k, v in metadata.items()
                if k not in {
                    "text", "chunk_id", "chunk_index", "start_offset", "end_offset",
                    "summary", "tags", "images", "image_refs",
                }
                and not str(k).startswith("_")
            }

            documents.append(DocumentInfo(
                doc_id=doc_id,
                title=title,
                source_path=source_path,
                chunk_count=len(chunks),
                first_chunk_id=first.get("id"),
                metadata=public_metadata,
            ))

        documents.sort(key=lambda d: (d.source_path or "", d.title, d.doc_id))
        return documents[:limit]

    def format_response(self, documents: List[DocumentInfo], collection: Optional[str]) -> str:
        name = collection or self.config.default_collection
        if not documents:
            return f"No documents found in collection `{name}`."

        lines = [
            f"## Documents in `{name}`",
            "",
            f"Returned `{len(documents)}` documents.",
            "",
        ]

        for i, doc in enumerate(documents, 1):
            lines.append(f"{i}. **{doc.title}**")
            lines.append(f"   - doc_id: `{doc.doc_id}`")
            if doc.source_path:
                lines.append(f"   - source: {doc.source_path}")
            lines.append(f"   - chunks: {doc.chunk_count}")
            if doc.first_chunk_id:
                lines.append(f"   - first_chunk_id: `{doc.first_chunk_id}`")

        return "\n".join(lines)

    async def execute(
        self,
        collection: Optional[str] = None,
        limit: int = 50,
    ) -> types.CallToolResult:
        logger.info("Executing list_documents (collection=%s, limit=%s)", collection, limit)
        try:
            documents = await asyncio.to_thread(self.list_documents, collection, limit)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_response(documents, collection))],
                isError=False,
            )
        except Exception as e:
            logger.exception("Error executing list_documents")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"## Error\n\n{str(e)}")],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    tool = ListDocumentsTool()

    async def handler(
        collection: Optional[str] = None,
        limit: int = 50,
    ) -> types.CallToolResult:
        return await tool.execute(collection=collection, limit=limit)

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
