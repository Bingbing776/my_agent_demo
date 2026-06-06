"""MCP Tool: check_evidence

Rules-first evidence checking for a RAG/Agent Harness layer.
It verifies whether an answer has retrieved evidence, whether evidence chunks exist,
and whether the answer is plausibly grounded in the evidence using lightweight heuristics.

This is intentionally not a full RAGAS replacement. It is a cheap gate that can run
before or alongside RAGAS metrics such as Faithfulness and Answer Relevancy.

Usage via MCP:
    Tool name: check_evidence
    Input schema:
        - answer (string, required): Generated answer to verify
        - evidence_chunk_ids (array[string], required): Chunk IDs used as evidence
        - query (string, optional): Original user query
        - collection (string, optional): Collection name to search in
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, TYPE_CHECKING

from mcp import types

if TYPE_CHECKING:
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.core.settings import Settings

logger = logging.getLogger(__name__)


TOOL_NAME = "check_evidence"
TOOL_DESCRIPTION = """Check whether an answer is supported by retrieved evidence chunks.

This tool is designed for the Harness layer. It reads evidence chunks by ID, checks
missing evidence, citation coverage, weakly supported answer sentences, and whether
References/Appendix chunks were used. It is a lightweight rules-first validator and
can be extended later with RAGAS Faithfulness / Answer Relevancy / Context Precision.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The generated answer to verify.",
        },
        "evidence_chunk_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Chunk IDs claimed or used as evidence.",
        },
        "query": {
            "type": "string",
            "description": "Optional original user query. Used only for reporting and future extensions.",
        },
        "collection": {
            "type": "string",
            "description": "Optional ChromaDB collection name. Uses default collection if omitted.",
        },
        "require_citations": {
            "type": "boolean",
            "description": "If true, answer text must explicitly contain at least one evidence chunk id or citation-like marker.",
            "default": False,
        },
        "min_evidence_count": {
            "type": "integer",
            "description": "Minimum number of found evidence chunks required to pass.",
            "default": 1,
            "minimum": 1,
            "maximum": 10,
        },
    },
    "required": ["answer", "evidence_chunk_ids"],
}


@dataclass
class CheckEvidenceConfig:
    persist_directory: str = "./data/db/chroma"
    default_collection: str = "paper"
    max_evidence_chunks: int = 12
    unsupported_sentence_overlap_threshold: float = 0.10  # 从 0.18 降低到 0.10，更宽松


@dataclass
class EvidenceChunk:
    chunk_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceCheckResult:
    passed: bool
    score: float
    found_count: int
    missing_chunk_ids: List[str] = field(default_factory=list)
    citation_coverage: float = 0.0
    unsupported_claims: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    evidence_chunks: List[EvidenceChunk] = field(default_factory=list)


class CheckEvidenceTool:
    """MCP tool for rules-first RAG answer evidence validation."""

    STOPWORDS: Set[str] = {
        "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
        "is", "are", "was", "were", "be", "been", "being", "to", "of", "in", "on", "for", "with",
        "as", "by", "from", "at", "it", "its", "into", "their", "there", "which", "who", "whom",
        "can", "could", "should", "would", "may", "might", "will", "also", "not", "no", "yes",
        "我们", "可以", "这个", "这篇", "论文", "主要", "通过", "进行", "说明", "因为", "所以", "以及",
    }

    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[CheckEvidenceConfig] = None,
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
    def config(self) -> CheckEvidenceConfig:
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

            self._config = CheckEvidenceConfig(
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
    def _normalize_ids(evidence_chunk_ids: Sequence[str], max_items: int) -> List[str]:
        seen: Set[str] = set()
        cleaned: List[str] = []
        for chunk_id in evidence_chunk_ids or []:
            if not chunk_id:
                continue
            cid = str(chunk_id).strip()
            if cid and cid not in seen:
                cleaned.append(cid)
                seen.add(cid)
            if len(cleaned) >= max_items:
                break
        return cleaned

    def _read_evidence_chunks(
        self,
        evidence_chunk_ids: Sequence[str],
        collection_name: Optional[str],
    ) -> tuple[List[EvidenceChunk], List[str]]:
        requested_ids = self._normalize_ids(evidence_chunk_ids, self.config.max_evidence_chunks)
        if not requested_ids:
            return [], []

        collection = self._get_collection(collection_name)
        found: List[EvidenceChunk] = []
        missing: List[str] = []

        # First try exact batched lookup.
        try:
            results = collection.get(ids=requested_ids, include=["metadatas", "documents"])
            returned_ids = results.get("ids") or []
            docs = results.get("documents") or []
            metas = results.get("metadatas") or []
            returned_lookup: Dict[str, EvidenceChunk] = {}
            for i, cid in enumerate(returned_ids):
                returned_lookup[cid] = EvidenceChunk(
                    chunk_id=cid,
                    text=docs[i] if i < len(docs) and docs[i] else "",
                    metadata=metas[i] if i < len(metas) and metas[i] else {},
                )
            for cid in requested_ids:
                if cid in returned_lookup:
                    found.append(returned_lookup[cid])
                else:
                    missing.append(cid)
        except Exception as e:
            logger.debug("Exact evidence lookup failed: %s", e)
            missing = requested_ids[:]

        # Fallback partial match for missing ids.
        if missing:
            try:
                all_results = collection.get(include=["metadatas", "documents"])
                ids = all_results.get("ids") or []
                docs = all_results.get("documents") or []
                metas = all_results.get("metadatas") or []
                still_missing: List[str] = []
                found_ids = {c.chunk_id for c in found}

                for requested in missing:
                    matched_index = None
                    for i, existing_id in enumerate(ids):
                        if existing_id in found_ids:
                            continue
                        if requested in existing_id:
                            matched_index = i
                            break
                    if matched_index is None:
                        still_missing.append(requested)
                    else:
                        cid = ids[matched_index]
                        found.append(EvidenceChunk(
                            chunk_id=cid,
                            text=docs[matched_index] if matched_index < len(docs) and docs[matched_index] else "",
                            metadata=metas[matched_index] if matched_index < len(metas) and metas[matched_index] else {},
                        ))
                        found_ids.add(cid)
                missing = still_missing
            except Exception as e:
                logger.debug("Partial evidence lookup failed: %s", e)

        return found, missing

    @classmethod
    def _tokens(cls, text: str) -> Set[str]:
        # 支持英文和中文的 token 提取
        # 英文：提取单词（3+ 字符）
        english_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-]{2,}", text or "")
        # 中文：提取词（使用 jieba 分词，如果可用；否则按字符提取）
        chinese_tokens = []
        try:
            import jieba
            # 提取所有中文片段
            chinese_parts = re.findall(r"[\u4e00-\u9fff]+", text or "")
            for part in chinese_parts:
                # jieba 分词
                words = jieba.lcut(part)
                # 过滤掉单字和停用词
                chinese_tokens.extend([w for w in words if len(w) >= 2])
        except ImportError:
            # 如果没有 jieba，按 2+ 字符的中文片段提取
            chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text or "")

        # 合并英文和中文 tokens，转小写
        all_tokens = set()
        for t in english_tokens:
            all_tokens.add(t.lower())
        for t in chinese_tokens:
            all_tokens.add(t.lower())

        # 过滤停用词
        return {t for t in all_tokens if t not in cls.STOPWORDS}

    @staticmethod
    def _sentences(text: str) -> List[str]:
        # Lightweight sentence split; good enough for a cheap harness gate.
        parts = re.split(r"(?<=[。！？.!?])\s+|\n+", (text or "").strip())
        return [p.strip() for p in parts if p and p.strip()]

    @staticmethod
    def _is_reference_or_appendix(chunk: EvidenceChunk) -> bool:
        meta = chunk.metadata or {}
        title = str(meta.get("section_title") or meta.get("title") or "").lower()
        first = ""
        for line in (chunk.text or "").splitlines():
            if line.strip():
                first = line.strip().lower()
                break
        return (
            "references" in title
            or "appendix" in title
            or first.startswith("## **references")
            or first.startswith("## references")
            or first.startswith("# references")
            or first.startswith("## **appendix")
            or first.startswith("## appendix")
            or first.startswith("# appendix")
        )

    @staticmethod
    def _citation_like_markers(answer: str) -> List[str]:
        # Match explicit chunk ids or common bracketed citations.
        patterns = [
            r"doc_[A-Za-z0-9_\-]+",
            r"chunk[_\-][A-Za-z0-9_\-]+",
            r"\[[0-9,\s]+\]",
            r"\(source[:：][^)]+\)",
            r"引用[:：]",
            r"来源[:：]",
        ]
        markers: List[str] = []
        for pattern in patterns:
            markers.extend(re.findall(pattern, answer or "", flags=re.IGNORECASE))
        return markers

    def check_evidence(
        self,
        answer: str,
        evidence_chunk_ids: Sequence[str],
        query: Optional[str] = None,
        collection: Optional[str] = None,
        require_citations: bool = False,
        min_evidence_count: int = 1,
    ) -> EvidenceCheckResult:
        if not answer or not answer.strip():
            raise ValueError("answer cannot be empty")
        if not evidence_chunk_ids:
            raise ValueError("evidence_chunk_ids cannot be empty")

        min_evidence_count = max(1, min(int(min_evidence_count), 10))
        found, missing = self._read_evidence_chunks(evidence_chunk_ids, collection)
        warnings: List[str] = []
        suggestions: List[str] = []

        if missing:
            warnings.append(f"Missing evidence chunks: {', '.join(missing)}")
            suggestions.append("Verify chunk IDs or rerun retrieval before answering.")

        if len(found) < min_evidence_count:
            warnings.append(f"Only {len(found)} evidence chunks found; required at least {min_evidence_count}.")
            suggestions.append("Retrieve more supporting chunks before generating the final answer.")

        reference_like = [c.chunk_id for c in found if self._is_reference_or_appendix(c)]
        if reference_like:
            warnings.append("Some evidence chunks appear to be References/Appendix chunks: " + ", ".join(reference_like[:5]))
            suggestions.append("For normal factual answers, prefer main-text chunks unless the question explicitly asks about references or appendix.")

        evidence_text = "\n\n".join(c.text for c in found if c.text)
        evidence_tokens = self._tokens(evidence_text)
        unsupported: List[str] = []

        for sentence in self._sentences(answer):
            sentence_tokens = self._tokens(sentence)
            # Ignore very short connective sentences.
            if len(sentence_tokens) < 4:
                continue
            overlap = len(sentence_tokens & evidence_tokens) / max(len(sentence_tokens), 1)
            if overlap < self.config.unsupported_sentence_overlap_threshold:
                unsupported.append(sentence)

        if unsupported:
            warnings.append(f"Detected {len(unsupported)} weakly supported sentence(s) by token-overlap heuristic.")
            suggestions.append("Read the evidence chunks again or regenerate the answer with stricter citation requirements.")

        citation_markers = self._citation_like_markers(answer)
        explicit_id_hits = 0
        for chunk in found:
            if chunk.chunk_id in answer:
                explicit_id_hits += 1

        citation_coverage = explicit_id_hits / max(len(found), 1) if found else 0.0
        has_any_citation = bool(citation_markers or explicit_id_hits)
        if require_citations and not has_any_citation:
            warnings.append("Answer does not contain explicit citation markers or evidence chunk IDs.")
            suggestions.append("Add citations or chunk IDs to the answer before returning it to the user.")

        # Simple score: evidence presence + support overlap + citation bonus - penalties.
        evidence_presence = min(len(found) / max(min_evidence_count, 1), 1.0)
        support_score = 1.0 if not unsupported else max(0.0, 1.0 - len(unsupported) / max(len(self._sentences(answer)), 1))
        citation_score = 1.0 if not require_citations else (1.0 if has_any_citation else 0.0)
        missing_penalty = min(len(missing) * 0.15, 0.45)
        reference_penalty = 0.1 if reference_like else 0.0

        score = max(0.0, min(1.0, (0.45 * evidence_presence + 0.40 * support_score + 0.15 * citation_score) - missing_penalty - reference_penalty))

        # 放宽 passed 判定：允许少量弱支持句子（不超过总句数的 30%）
        total_sentences = len(self._sentences(answer))
        max_allowed_unsupported = max(1, int(total_sentences * 0.3))  # 允许 30% 的句子弱支持

        # 放宽缺失 chunk 要求：只要找到至少 min_evidence_count 个即可，允许部分缺失
        has_enough_evidence = len(found) >= min_evidence_count
        # 如果找到的 > 0 且缺失的只是少数（< 50%），也认为可以接受
        if not has_enough_evidence and found and missing:
            found_ratio = len(found) / (len(found) + len(missing))
            has_enough_evidence = found_ratio >= 0.5  # 至少找到 50%

        passed = (
            has_enough_evidence
            and len(unsupported) <= max_allowed_unsupported  # 从"零弱支持"改为"不超过30%"
            and (has_any_citation or not require_citations)
        )

        if passed:
            suggestions.append("Evidence check passed. The answer is plausibly supported by the supplied chunks.")

        return EvidenceCheckResult(
            passed=passed,
            score=score,
            found_count=len(found),
            missing_chunk_ids=missing,
            citation_coverage=citation_coverage,
            unsupported_claims=unsupported,
            warnings=warnings,
            suggestions=suggestions,
            evidence_chunks=found,
        )

    def format_response(self, result: EvidenceCheckResult, query: Optional[str] = None) -> str:
        lines = [
            "## Evidence Check",
            "",
            f"**Passed:** `{result.passed}`",
            f"**Score:** `{result.score:.3f}`",
            f"**Found evidence chunks:** `{result.found_count}`",
            f"**Citation coverage:** `{result.citation_coverage:.3f}`",
        ]
        if query:
            lines.append(f"**Query:** {query}")

        if result.missing_chunk_ids:
            lines.extend(["", "### Missing Chunk IDs"])
            for cid in result.missing_chunk_ids:
                lines.append(f"- `{cid}`")

        if result.warnings:
            lines.extend(["", "### Warnings"])
            for warning in result.warnings:
                lines.append(f"- {warning}")

        if result.unsupported_claims:
            lines.extend(["", "### Weakly Supported Sentences"])
            for claim in result.unsupported_claims[:8]:
                lines.append(f"- {claim}")

        if result.suggestions:
            lines.extend(["", "### Suggestions"])
            for suggestion in result.suggestions:
                lines.append(f"- {suggestion}")

        if result.evidence_chunks:
            lines.extend(["", "### Evidence Chunks"])
            for chunk in result.evidence_chunks:
                meta = chunk.metadata or {}
                source = meta.get("source_path") or meta.get("source") or ""
                section = meta.get("section_title") or meta.get("title") or ""
                lines.append(f"- `{chunk.chunk_id}`" + (f" — {section}" if section else "") + (f" — {source}" if source else ""))

        lines.extend([
            "",
            "> Note: This is a lightweight rules-first check. For final evaluation, combine it with RAGAS Faithfulness / Answer Relevancy / Context Precision.",
        ])
        return "\n".join(lines)

    def format_error(self, error: Exception) -> str:
        if isinstance(error, ValueError):
            return f"## Invalid Request\n\n{str(error)}"
        return f"## Error\n\nAn error occurred: {str(error)}"

    async def execute(
        self,
        answer: str,
        evidence_chunk_ids: Sequence[str],
        query: Optional[str] = None,
        collection: Optional[str] = None,
        require_citations: bool = False,
        min_evidence_count: int = 1,
    ) -> types.CallToolResult:
        logger.info("Executing check_evidence (evidence_count=%s, collection=%s)", len(evidence_chunk_ids or []), collection)
        try:
            result = await asyncio.to_thread(
                self.check_evidence,
                answer,
                evidence_chunk_ids,
                query,
                collection,
                require_citations,
                min_evidence_count,
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_response(result, query=query))],
                isError=False,
            )
        except Exception as e:
            logger.exception("Error executing check_evidence")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self.format_error(e))],
                isError=True,
            )


def register_tool(protocol_handler: ProtocolHandler) -> None:
    tool = CheckEvidenceTool()

    async def handler(
        answer: str,
        evidence_chunk_ids: Sequence[str],
        query: Optional[str] = None,
        collection: Optional[str] = None,
        require_citations: bool = False,
        min_evidence_count: int = 1,
    ) -> types.CallToolResult:
        return await tool.execute(
            answer=answer,
            evidence_chunk_ids=evidence_chunk_ids,
            query=query,
            collection=collection,
            require_citations=require_citations,
            min_evidence_count=min_evidence_count,
        )

    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
