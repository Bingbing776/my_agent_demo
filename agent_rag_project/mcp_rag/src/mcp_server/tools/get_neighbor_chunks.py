"""MCP Tool: get_neighbor_chunks

Read a target chunk and its neighboring chunks from the same document.
This is useful when a retrieved chunk needs local context, such as table captions,
figure explanations, or surrounding paragraphs.

Usage via MCP:
    Tool name: get_neighbor_chunks
    Input schema:
        - chunk_id (string, required): Target chunk ID
        - window (integer, optional): Number of chunks before and after target
        - collection (string, optional): Collection name
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


TOOL_NAME = "get_neighbor_chunks"
TOOL_DESCRIPTION = """Read a chunk together with neighboring chunks from the same document.

Use this after retrieval when the Agent needs surrounding evidence, for example
when a table caption, figure caption, or explanatory paragraph is in an adjacent chunk.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunk_id": {
            "type": "string",
            "description": "The target chunk ID.",
        },
        "window": {
            "type": "integer",
            "description": "Number of chunks before and after the target chunk.",
            "default": 1,
            "minimum": 0,
            "maximum": 5,
        },
        "collection": {
            "type": "string",
            "description": "Optional ChromaDB collection name. Uses default collection if omitted.",
        },
    },
    "required": ["chunk_id"],
}


@dataclass
class NeighborChunksConfig:
    persist_directory: str = "./data/db/chroma"
    default_collection: str = "paper"
    max_window: int = 5


@dataclass
class NeighborChunk:
    chunk_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    relative_position: int = 0


class NeighborChunksNotFoundError(Exception):
    pass


class GetNeighborChunksTool:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[NeighborChunksConfig] = None,
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
    def config(self) -> NeighborChunksConfig:
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

            self._config = NeighborChunksConfig(
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
    def _doc_key(chunk_id: str, metadata: Dict[str, Any]) -> str:
        # source_ref is the most reliable parent document pointer in your pipeline.
        if metadata.get("source_ref"):
            return f"source_ref::{metadata['source_ref']}"
        if metadata.get("source_path"):
            return f"source_path::{metadata['source_path']}"
        if metadata.get("source"):
            return f"source::{metadata['source']}"
        # Fallback for generated ids like doc_xxx_0001_hash or sourcehash_0001_hash.
        parts = chunk_id.split("_")
        if len(parts) >= 3 and parts[-2].isdigit():
            return "id_prefix::" + "_".join(parts[:-2])
        return f"chunk_id::{chunk_id}"

    def _load_all_chunks(self, collection_name: Optional[str]) -> List[Dict[str, Any]]:
        collection = self._get_collection(collection_name)
        results = collection.get(include=["metadatas", "documents"])
        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []

        chunks: List[Dict[str, Any]] = []
        for i, chunk_id in enumerate(ids):
            metadata = metas[i] if i < len(metas) and metas[i] else {}
            chunks.append({
                "id": chunk_id,
                "text": docs[i] if i < len(docs) and docs[i] else "",
                "metadata": metadata,
            })
        return chunks

    def get_neighbor_chunks(
        self,
        chunk_id: str,
        window: int = 1,
        collection: Optional[str] = None,
    ) -> List[NeighborChunk]:
        if not chunk_id or not chunk_id.strip():
            raise ValueError("chunk_id cannot be empty")

        window = max(0, min(int(window), self.config.max_window))
        chunk_id = chunk_id.strip()

        all_chunks = self._load_all_chunks(collection)
        if not all_chunks:
            raise NeighborChunksNotFoundError("No chunks found in the collection.")

        target = None
        for chunk in all_chunks:
            if chunk["id"] == chunk_id:
                target = chunk
                break

        # Fallback partial match.
        if target is None:
            for chunk in all_chunks:
                if chunk_id in chunk["id"]:
                    target = chunk
                    chunk_id = chunk["id"]
                    break

        if target is None:
            raise NeighborChunksNotFoundError(f"Target chunk '{chunk_id}' not found.")

        target_key = self._doc_key(target["id"], target.get("metadata", {}))
        doc_chunks = [
            c for c in all_chunks
            if self._doc_key(c["id"], c.get("metadata", {})) == target_key
        ]

        doc_chunks.sort(
            key=lambda c: (
                self._to_int(c.get("metadata", {}).get("chunk_index"), 10**9),
                c["id"],
            )
        )

        target_pos = next((i for i, c in enumerate(doc_chunks) if c["id"] == chunk_id), None)
        if target_pos is None:
            raise NeighborChunksNotFoundError(f"Target chunk '{chunk_id}' not found in its document group.")

        start = max(0, target_pos - window)
        end = min(len(doc_chunks), target_pos + window + 1)

        neighbors: List[NeighborChunk] = []
        for pos in range(start, end):
            c = doc_chunks[pos]
            neighbors.append(NeighborChunk(
                chunk_id=c["id"],
                text=c.get("text", ""),
                metadata=c.get("metadata", {}),
                relative_position=pos - target_pos,
            ))

        return neighbors

    def format_response(self, chunks: List[NeighborChunk]) -> str:
        if not chunks:
            return "No neighboring chunks found."

        lines = [
            "## Neighbor Chunks",
            "",
            f"Returned `{len(chunks)}` chunks.",
        ]

        for item in chunks:
            metadata = item.metadata or {}
            marker = "TARGET" if item.relative_position == 0 else f"{item.relative_position:+d}"
            lines.extend([
                "",
                "---",
                "",
                f"### Chunk `{item.chunk_id}` ({marker})",
            ])

            source = metadata.get("source_path") or metadata.get("source")
            if source:
                lines.append(f"**Source:** {source}")
            if "chunk_index" in metadata:
                lines.append(f"**chunk_index:** {metadata.get('chunk_index')}")
            if "title" in metadata:
                lines.append(f"**title:** {metadata.get('title')}")
            if "section_title" in metadata:
                lines.append(f"**section_title:** {metadata.get('section_title')}")

            lines.extend(["", item.text or "No text stored."])

        return "\n".join(lines)

    def format_error(self, error: Exception) -> str:
        if isinstance(error, ValueError):
            return f"## Invalid Request\n\n{str(error)}"
        return f"## Error\n\n{str(error)}"

    async def execute(
        self,
        chunk_id: str,
        window: int = 1,
        collection: Optional[str] = None,
    ) -> types.CallToolResult:
        logger.info(
            "Executing get_neighbor_chunks (chunk_id=%s, window=%s, collection=%s)",
            chunk_id,
            window,
            collection,
        )
        try:
            chunks = await asyncio.to_thread(
                self.get_neighbor_chunks,
                chunk_id,
                window,
                collection,
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_response(chunks))],
                isError=False,
            )
        except Exception as e:
            logger.exception("Error executing get_neighbor_chunks")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_error(e))],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    tool = GetNeighborChunksTool()

    async def handler(
        chunk_id: str,
        window: int = 1,
        collection: Optional[str] = None,
    ) -> types.CallToolResult:
        return await tool.execute(
            chunk_id=chunk_id,
            window=window,
            collection=collection,
        )

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
