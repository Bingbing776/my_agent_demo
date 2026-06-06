"""MCP Tool: get_document_outline

Build a lightweight structural outline for one document stored in ChromaDB.
This is a document-map tool for Agent/RAG Harness workflows.

Usage via MCP:
    Tool name: get_document_outline
    Input schema:
        - doc_id (string, required): Parent document id / source_ref to inspect
        - collection (string, optional): Collection name to search in
        - include_previews (boolean, optional): Include short chunk previews
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "get_document_outline"
TOOL_DESCRIPTION = """Get a structural outline for a document.

Returns sections, table chunks, figure/image chunks, References chunks, and
Appendix chunks for a document. Use this before long-form document analysis,
section-level summarization, table QA, image/figure QA, or multi-document comparison.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "doc_id": {
            "type": "string",
            "description": "Document ID / source_ref. Full doc_id is preferred, but partial matching is supported.",
        },
        "collection": {
            "type": "string",
            "description": "Optional ChromaDB collection name. Uses default collection if omitted.",
        },
        "include_previews": {
            "type": "boolean",
            "description": "Whether to include short text previews for section/table/figure chunks.",
            "default": False,
        },
    },
    "required": ["doc_id"],
}


@dataclass
class DocumentOutlineConfig:
    persist_directory: str = "./data/db/chroma"
    default_collection: str = "paper"
    preview_chars: int = 180


@dataclass
class OutlineSection:
    title: str
    level: int
    chunk_ids: List[str] = field(default_factory=list)
    chunk_indexes: List[int] = field(default_factory=list)
    preview: Optional[str] = None


@dataclass
class OutlineItem:
    caption: str
    chunk_id: str
    chunk_index: int = 0
    image_ids: List[str] = field(default_factory=list)
    preview: Optional[str] = None


@dataclass
class DocumentOutline:
    doc_id: str
    title: str
    source_path: Optional[str]
    chunk_count: int
    sections: List[OutlineSection] = field(default_factory=list)
    tables: List[OutlineItem] = field(default_factory=list)
    figures: List[OutlineItem] = field(default_factory=list)
    references_chunk_ids: List[str] = field(default_factory=list)
    appendix_chunk_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DocumentOutlineNotFoundError(Exception):
    def __init__(self, doc_id: str, collection: Optional[str] = None):
        message = f"Document '{doc_id}' not found"
        if collection:
            message += f" in collection '{collection}'"
        super().__init__(message)
        self.doc_id = doc_id
        self.collection = collection


class GetDocumentOutlineTool:
    """MCP tool that derives a document outline from stored chunks."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[DocumentOutlineConfig] = None,
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
    def config(self) -> DocumentOutlineConfig:
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

            self._config = DocumentOutlineConfig(
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
    def _clean_heading(raw: str) -> str:
        text = raw.strip()
        text = re.sub(r"^#{1,6}\s+", "", text)
        text = text.replace("**", "").replace("__", "").replace("`", "")
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip() or "Untitled Section"

    @staticmethod
    def _preview(text: str, max_chars: int) -> str:
        compact = re.sub(r"\s+", " ", (text or "").strip())
        if len(compact) > max_chars:
            compact = compact[: max_chars - 3] + "..."
        return compact

    @staticmethod
    def _extract_headings(text: str) -> List[Dict[str, Any]]:
        headings: List[Dict[str, Any]] = []
        for line in (text or "").splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.strip())
            if match:
                headings.append({
                    "level": len(match.group(1)),
                    "title": GetDocumentOutlineTool._clean_heading(line),
                })
        return headings

    @staticmethod
    def _looks_like_table(text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        pipe_lines = [line for line in lines if line.count("|") >= 2]
        return len(pipe_lines) >= 2

    @staticmethod
    def _extract_table_caption(text: str) -> Optional[str]:
        for line in (text or "").splitlines():
            s = line.strip()
            if re.match(r"^Table\s+\d+[\.:\s]", s, flags=re.IGNORECASE):
                return s
        return None

    @staticmethod
    def _extract_figure_caption(text: str) -> Optional[str]:
        for line in (text or "").splitlines():
            s = line.strip()
            if re.match(r"^(Figure|Fig\.)\s+\d+[\.:\s]", s, flags=re.IGNORECASE):
                return s
        return None

    @staticmethod
    def _extract_image_ids(text: str) -> List[str]:
        return [m.strip() for m in re.findall(r"\[IMAGE:\s*([^\]]+)\]", text or "")]

    @staticmethod
    def _is_references_chunk(text: str, metadata: Dict[str, Any]) -> bool:
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
        return "appendix" in title or first.startswith("## **appendix") or first.startswith("## appendix") or first.startswith("# appendix")

    def _load_document_chunks(self, doc_id: str, collection_name: Optional[str]) -> List[Dict[str, Any]]:
        collection = self._get_collection(collection_name)
        doc_id = doc_id.strip()

        # Strategy 1: source_ref exact match.
        try:
            results = collection.get(where={"source_ref": doc_id}, include=["metadatas", "documents"])
            chunks = self._records_from_results(results)
            if chunks:
                return chunks
        except Exception as e:
            logger.debug("source_ref lookup failed: %s", e)

        # Strategy 2: scan collection and match source_ref/doc_id/source_path/chunk id.
        results = collection.get(include=["metadatas", "documents"])
        all_chunks = self._records_from_results(results)
        chunks: List[Dict[str, Any]] = []
        for chunk in all_chunks:
            meta = chunk.get("metadata", {}) or {}
            candidates = [
                str(meta.get("source_ref", "")),
                str(meta.get("doc_id", "")),
                str(meta.get("source_path", "")),
                str(meta.get("source", "")),
                str(chunk.get("id", "")),
            ]
            if any(doc_id == c or doc_id in c for c in candidates if c):
                chunks.append(chunk)
        return chunks

    @staticmethod
    def _records_from_results(results: Dict[str, Any]) -> List[Dict[str, Any]]:
        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        chunks: List[Dict[str, Any]] = []
        for i, chunk_id in enumerate(ids):
            chunks.append({
                "id": chunk_id,
                "text": docs[i] if i < len(docs) and docs[i] else "",
                "metadata": metas[i] if i < len(metas) and metas[i] else {},
            })
        return chunks

    def get_document_outline(
        self,
        doc_id: str,
        collection: Optional[str] = None,
        include_previews: bool = False,
    ) -> DocumentOutline:
        if not doc_id or not doc_id.strip():
            raise ValueError("doc_id cannot be empty")

        chunks = self._load_document_chunks(doc_id, collection)
        if not chunks:
            raise DocumentOutlineNotFoundError(doc_id, collection)

        chunks.sort(key=lambda c: (self._to_int(c.get("metadata", {}).get("chunk_index"), 10**9), c["id"]))
        first_meta = chunks[0].get("metadata", {}) or {}

        title = str(first_meta.get("title") or "").strip()
        if not title:
            first_headings = self._extract_headings(chunks[0].get("text", ""))
            title = first_headings[0]["title"] if first_headings else "Untitled Document"

        source_path = first_meta.get("source_path") or first_meta.get("source")
        resolved_doc_id = str(first_meta.get("source_ref") or first_meta.get("doc_id") or doc_id)

        sections: List[OutlineSection] = []
        current_section: Optional[OutlineSection] = None
        tables: List[OutlineItem] = []
        figures: List[OutlineItem] = []
        references_chunk_ids: List[str] = []
        appendix_chunk_ids: List[str] = []

        for chunk in chunks:
            chunk_id = chunk["id"]
            text = chunk.get("text", "") or ""
            metadata = chunk.get("metadata", {}) or {}
            chunk_index = self._to_int(metadata.get("chunk_index"), 0)

            if self._is_references_chunk(text, metadata):
                references_chunk_ids.append(chunk_id)
            if self._is_appendix_chunk(text, metadata):
                appendix_chunk_ids.append(chunk_id)

            headings = self._extract_headings(text)
            if headings:
                # If a chunk contains multiple headings, register each heading.
                for heading in headings:
                    section = OutlineSection(
                        title=heading["title"],
                        level=heading["level"],
                        chunk_ids=[chunk_id],
                        chunk_indexes=[chunk_index],
                        preview=self._preview(text, self.config.preview_chars) if include_previews else None,
                    )
                    sections.append(section)
                    current_section = section
            elif current_section is not None:
                current_section.chunk_ids.append(chunk_id)
                current_section.chunk_indexes.append(chunk_index)
            else:
                current_section = OutlineSection(
                    title="Front Matter",
                    level=1,
                    chunk_ids=[chunk_id],
                    chunk_indexes=[chunk_index],
                    preview=self._preview(text, self.config.preview_chars) if include_previews else None,
                )
                sections.append(current_section)

            table_caption = self._extract_table_caption(text)
            if table_caption or self._looks_like_table(text):
                tables.append(OutlineItem(
                    caption=table_caption or "Table-like content",
                    chunk_id=chunk_id,
                    chunk_index=chunk_index,
                    preview=self._preview(text, self.config.preview_chars) if include_previews else None,
                ))

            image_ids = self._extract_image_ids(text)
            figure_caption = self._extract_figure_caption(text)
            if image_ids or figure_caption:
                figures.append(OutlineItem(
                    caption=figure_caption or "Image/Figure content",
                    chunk_id=chunk_id,
                    chunk_index=chunk_index,
                    image_ids=image_ids,
                    preview=self._preview(text, self.config.preview_chars) if include_previews else None,
                ))

        return DocumentOutline(
            doc_id=resolved_doc_id,
            title=title,
            source_path=str(source_path) if source_path else None,
            chunk_count=len(chunks),
            sections=sections,
            tables=tables,
            figures=figures,
            references_chunk_ids=references_chunk_ids,
            appendix_chunk_ids=appendix_chunk_ids,
            metadata={
                "collection": collection or self.config.default_collection,
                "requested_doc_id": doc_id,
            },
        )

    def format_response(self, outline: DocumentOutline) -> str:
        lines = [
            f"## Document Outline: {outline.title}",
            "",
            f"**Document ID:** `{outline.doc_id}`",
        ]
        if outline.source_path:
            lines.append(f"**Source:** {outline.source_path}")
        lines.append(f"**Chunks:** {outline.chunk_count}")

        lines.extend(["", "### Sections"])
        if outline.sections:
            for i, section in enumerate(outline.sections, 1):
                indent = "  " * max(section.level - 1, 0)
                chunk_range = ", ".join(f"`{cid}`" for cid in section.chunk_ids[:6])
                if len(section.chunk_ids) > 6:
                    chunk_range += f", ... +{len(section.chunk_ids) - 6} more"
                lines.append(f"{i}. {indent}**{section.title}** — chunks: {chunk_range}")
                if section.preview:
                    lines.append(f"   Preview: {section.preview}")
        else:
            lines.append("No section headings detected.")

        lines.extend(["", "### Tables"])
        if outline.tables:
            for item in outline.tables:
                lines.append(f"- **{item.caption}** — chunk `{item.chunk_id}`")
                if item.preview:
                    lines.append(f"  Preview: {item.preview}")
        else:
            lines.append("No table-like chunks detected.")

        lines.extend(["", "### Figures / Images"])
        if outline.figures:
            for item in outline.figures:
                image_part = f" images={item.image_ids}" if item.image_ids else ""
                lines.append(f"- **{item.caption}** — chunk `{item.chunk_id}`{image_part}")
                if item.preview:
                    lines.append(f"  Preview: {item.preview}")
        else:
            lines.append("No image/figure chunks detected.")

        if outline.references_chunk_ids:
            refs = ", ".join(f"`{cid}`" for cid in outline.references_chunk_ids[:10])
            lines.extend(["", "### References Chunks", refs])

        if outline.appendix_chunk_ids:
            apps = ", ".join(f"`{cid}`" for cid in outline.appendix_chunk_ids[:10])
            lines.extend(["", "### Appendix Chunks", apps])

        return "\n".join(lines)

    def format_error(self, error: Exception) -> str:
        if isinstance(error, DocumentOutlineNotFoundError):
            return f"## Document Not Found\n\n{str(error)}\n\nPlease verify the doc_id and collection name."
        if isinstance(error, ValueError):
            return f"## Invalid Request\n\n{str(error)}"
        return f"## Error\n\nAn error occurred: {str(error)}"

    async def execute(
        self,
        doc_id: str,
        collection: Optional[str] = None,
        include_previews: bool = False,
    ) -> types.CallToolResult:
        logger.info("Executing get_document_outline (doc_id=%s, collection=%s)", doc_id, collection)
        try:
            outline = await asyncio.to_thread(
                self.get_document_outline,
                doc_id,
                collection,
                include_previews,
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_response(outline))],
                isError=False,
            )
        except Exception as e:
            logger.exception("Error executing get_document_outline")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_error(e))],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    tool = GetDocumentOutlineTool()

    async def handler(
        doc_id: str,
        collection: Optional[str] = None,
        include_previews: bool = False,
    ) -> types.CallToolResult:
        return await tool.execute(
            doc_id=doc_id,
            collection=collection,
            include_previews=include_previews,
        )

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
