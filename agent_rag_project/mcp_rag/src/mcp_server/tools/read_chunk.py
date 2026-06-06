"""MCP Tool: read_chunk

Read one chunk from the ChromaDB-backed knowledge base by chunk_id.
This is an evidence-reading tool for an Agent/RAG Harness layer.

Usage via MCP:
    Tool name: read_chunk
    Input schema:
        - chunk_id (string, required): Chunk ID to read
        - collection (string, optional): Collection name to search in
        - allow_partial_match (boolean, optional): Allow fallback partial ID match
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "read_chunk"
TOOL_DESCRIPTION = """Read a single chunk by chunk_id.

Returns the chunk text and metadata. Use this after retrieval when the Agent
needs to inspect exact evidence before answering.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunk_id": {
            "type": "string",
            "description": "The chunk ID to read. Exact IDs are preferred.",
        },
        "collection": {
            "type": "string",
            "description": "Optional ChromaDB collection name. Uses default collection if omitted.",
        },
        "allow_partial_match": {
            "type": "boolean",
            "description": "If true, falls back to partial chunk_id matching when exact lookup fails.",
            "default": True,
        },
    },
    "required": ["chunk_id"],
}


@dataclass
class ReadChunkConfig:
    persist_directory: str = "./data/db/chroma"
    default_collection: str = "paper"


@dataclass
class ChunkDetail:
    chunk_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "metadata": self.metadata,
        }


class ChunkNotFoundError(Exception):
    def __init__(self, chunk_id: str, collection: Optional[str] = None):
        message = f"Chunk '{chunk_id}' not found"
        if collection:
            message += f" in collection '{collection}'"
        super().__init__(message)
        self.chunk_id = chunk_id
        self.collection = collection


class ReadChunkTool:
    """MCP tool for reading one chunk from ChromaDB."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[ReadChunkConfig] = None,
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
    def config(self) -> ReadChunkConfig:
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

            self._config = ReadChunkConfig(
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
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )
        return self._chroma_client

    def _get_collection(self, collection_name: Optional[str] = None) -> Any:
        client = self._get_chroma_client()
        name = collection_name or self.config.default_collection
        try:
            return client.get_collection(name=name)
        except Exception as e:
            raise ValueError(f"Collection '{name}' does not exist: {e}") from e

    def _record_from_chroma_get(self, results: Dict[str, Any], index: int = 0) -> Optional[ChunkDetail]:
        ids = results.get("ids") or []
        if not ids:
            return None

        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []

        chunk_id = ids[index]
        text = documents[index] if index < len(documents) and documents[index] else ""
        metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        return ChunkDetail(chunk_id=chunk_id, text=text, metadata=metadata)

    def read_chunk(
        self,
        chunk_id: str,
        collection: Optional[str] = None,
        allow_partial_match: bool = True,
    ) -> ChunkDetail:
        if not chunk_id or not chunk_id.strip():
            raise ValueError("chunk_id cannot be empty")

        chunk_id = chunk_id.strip()
        chroma_collection = self._get_collection(collection)

        # Strategy 1: exact ID lookup.
        results = chroma_collection.get(
            ids=[chunk_id],
            include=["metadatas", "documents"],
        )
        detail = self._record_from_chroma_get(results)
        if detail:
            return detail

        # Strategy 2: fallback partial matching.
        if allow_partial_match:
            all_results = chroma_collection.get(include=["metadatas", "documents"])
            ids = all_results.get("ids") or []
            for i, existing_id in enumerate(ids):
                if chunk_id in existing_id:
                    return self._record_from_chroma_get(all_results, i)  # type: ignore[arg-type]

        raise ChunkNotFoundError(chunk_id, collection)

    def format_response(self, detail: ChunkDetail) -> str:
        metadata = detail.metadata or {}

        lines = [
            "## Chunk Detail",
            "",
            f"**Chunk ID:** `{detail.chunk_id}`",
        ]

        source = metadata.get("source_path") or metadata.get("source")
        if source:
            lines.append(f"**Source:** {source}")

        for key in ["title", "section_title", "chunk_index", "page", "page_num", "doc_type", "source_ref"]:
            if key in metadata and metadata[key] not in (None, ""):
                lines.append(f"**{key}:** {metadata[key]}")

        lines.extend([
            "",
            "### Text",
            "",
            detail.text or "No text stored for this chunk.",
            "",
            "### Metadata",
            "",
        ])

        if metadata:
            for key, value in metadata.items():
                lines.append(f"- **{key}:** {value}")
        else:
            lines.append("No metadata available.")

        return "\n".join(lines)

    def format_error(self, error: Exception) -> str:
        if isinstance(error, ChunkNotFoundError):
            return f"## Chunk Not Found\n\n{str(error)}\n\nPlease verify the chunk_id and collection name."
        if isinstance(error, ValueError):
            return f"## Invalid Request\n\n{str(error)}"
        return f"## Error\n\nAn error occurred: {str(error)}"

    async def execute(
        self,
        chunk_id: str,
        collection: Optional[str] = None,
        allow_partial_match: bool = True,
    ) -> types.CallToolResult:
        logger.info(
            "Executing read_chunk (chunk_id=%s, collection=%s)",
            chunk_id,
            collection,
        )
        try:
            detail = await asyncio.to_thread(
                self.read_chunk,
                chunk_id,
                collection,
                allow_partial_match,
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_response(detail))],
                isError=False,
            )
        except Exception as e:
            logger.exception("Error executing read_chunk")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_error(e))],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    tool = ReadChunkTool()

    async def handler(
        chunk_id: str,
        collection: Optional[str] = None,
        allow_partial_match: bool = True,
    ) -> types.CallToolResult:
        return await tool.execute(
            chunk_id=chunk_id,
            collection=collection,
            allow_partial_match=allow_partial_match,
        )

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
