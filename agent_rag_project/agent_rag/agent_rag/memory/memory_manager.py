"""Memory manager for Agent RAG (short / long / episodic memory)."""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


class MemoryManager:
    def __init__(
        self,
        long_term_collection=None,
        sqlite_conn=None,
        qdrant_collection=None,
        config: Optional[Dict[str, Any]] = None,
    ):
        cfg = config or {}
        self._short_term_memory: List[dict] = []
        self._short_term_capacity = int(cfg.get("short_term_capacity", 50))
        self._long_term_collection = long_term_collection
        self.sqlite_conn = sqlite_conn
        self.qdrant_collection = qdrant_collection
        self._threshold = float(cfg.get("threshold", 0.7))
        self._compress_max_tokens = int(cfg.get("compress_truncate_n", 512))
        self._w_time = float(cfg.get("w_time", 0.3))
        self._w_importance = float(cfg.get("w_importance", 0.5))
        self._w_freq = float(cfg.get("w_freq", 0.2))
        self._top_k_short = int(cfg.get("short_term_k", 5))
        self._top_k_long = int(cfg.get("long_term_k", 3))
        self._top_k_episodic = int(cfg.get("episodic_k", 2))
        self._encoder = None
        self._llm = None

    @property
    def long_term_collection(self):
        return self._long_term_collection

    @property
    def short_term_capacity(self) -> int:
        return self._short_term_capacity

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def compress_truncate_n(self) -> int:
        return self._compress_max_tokens

    @property
    def w_time(self) -> float:
        return self._w_time

    @property
    def w_importance(self) -> float:
        return self._w_importance

    @property
    def w_freq(self) -> float:
        return self._w_freq

    @property
    def short_term_k(self) -> int:
        return self._top_k_short

    @property
    def long_term_k(self) -> int:
        return self._top_k_long

    @property
    def episodic_k(self) -> int:
        return self._top_k_episodic

    def _get_llm(self):
            """
            延迟初始化 LLM 实例。

            使用 src.libs.llm.llm_factory.LLMFactory.create 并传入 Settings 对象。
            若创建失败则使用 stub。
            """
            if self._llm is not None:
                return self._llm

            try:
                from src.libs.llm.llm_factory import LLMFactory
                from src.core.settings import load_settings

                settings = None
                try:
                    from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
                except TypeError:
                    try:
                        from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
                    except Exception:
                        settings = None
                except Exception:
                    try:
                        settings = Settings()
                    except Exception:
                        settings = None

                if settings is not None:
                    self._llm = LLMFactory.create(settings)
                else:
                    raise RuntimeError("Cannot load Settings")
            except Exception:
                from src.libs.llm.base_llm import ChatResponse

                class _StubLLM:
                    def chat(self, messages, **kwargs):
                        return ChatResponse(content='stub summary', model='stub')

                self._llm = _StubLLM()

            return self._llm

    def _get_encoder(self):
            """
            延迟初始化 DenseEncoder。
            """
            if self._encoder is not None:
                return self._encoder

            try:
                from src.core.types import Chunk
                from src.ingestion.embedding.dense_encoder import DenseEncoder

                class _TextEncoderAdapter:
                    def __init__(self, dense):
                        self._dense = dense

                    def encode(self, text: str):
                        t = (text or "").strip() or " "
                        vecs = self._dense.encode([Chunk(id="0", text=t, metadata={"source_path": "memory"})])
                        if not vecs:
                            return []
                        return list(vecs[0])

                try:
                    from src.libs.embedding.embedding_factory import EmbeddingFactory
                    from src.core.settings import load_settings

                    settings = None
                    try:
                        from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
                    except TypeError:
                        from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
                    except Exception:
                        try:
                            settings = Settings()
                        except Exception:
                            settings = None

                    embedding = EmbeddingFactory.create(settings)
                    self._encoder = _TextEncoderAdapter(
                        DenseEncoder(embedding=embedding, batch_size=10)
                    )
                except Exception:
                    raise
            except Exception:
                class _StubEncoder:
                    def encode(self, text: str):
                        t = (text or "").strip() or " "
                        vec = [0.0] * 384
                        for i, ch in enumerate(t):
                            vec[i % 384] += ((ord(ch) % 97) + 1) / 100.0
                        if not any(vec):
                            vec[0] = 0.1
                        return vec

                self._encoder = _StubEncoder()

            return self._encoder

    def _evidence_body(self, c: dict) -> str:
            """
            优先 text_snippet，否则 text；都为空时返回空串。
            兼容 body 作为兜底字段。
            """
            if not isinstance(c, dict) or not c:
                return ""

            text_snippet = c.get("text_snippet")
            if text_snippet is not None:
                text_snippet = str(text_snippet).strip()
                if text_snippet:
                    return text_snippet

            text = c.get("text")
            if text is not None:
                text = str(text).strip()
                if text:
                    return text

            body = c.get("body")
            if body is not None:
                body = str(body).strip()
                if body:
                    return body

            return ""

    def _evidence_chunks_from_result(self, result: dict) -> List[dict]:
            """
            将 result 归一为 [{"chunk_id", "source", "text_snippet"}, ...]。
            citations 非空时逐项抽取；否则退化为基于 result["text"] 的单条记录。
            """
            if not isinstance(result, dict):
                return []

            citations = result.get("citations") or []
            if not citations:
                structured = result.get("structuredContent")
                if isinstance(structured, dict):
                    citations = structured.get("citations") or []
            chunks: List[dict] = []

            if citations:
                for c in citations:
                    if not isinstance(c, dict):
                        continue
                    body = self._evidence_body(c)
                    if not body:
                        continue
                    chunks.append(
                        {
                            "chunk_id": str(c.get("chunk_id") or ""),
                            "source": str(c.get("source") or c.get("doc_id") or ""),
                            "text_snippet": body,
                        }
                    )
                return chunks

            body = str(result.get("text") or "").strip()
            if not body:
                return []

            return [
                {
                    "chunk_id": "",
                    "source": str(result.get("source") or result.get("tool") or result.get("tool_name") or ""),
                    "text_snippet": body,
                }
            ]

    def compute_memory_similarity(self, chunks: List[dict], query_text: str) -> Tuple[float, List[dict]]:
            """
            计算 memory_item 内多个 chunk 与 query 的整体相似度，并返回每个 chunk 的 embedding。

            Args:
                chunks: 每项为 dict；用于 encode 的正文取 self._evidence_body(chunk)。
                query_text: 当前 query。

            Returns:
                (score: 0~1, [{"chunk_id": ..., "source": ..., "embedding": [...]}, ...])
            """
            if not chunks:
                return 0.0, []

            encoder = self._get_encoder()
            query = (query_text or "").strip()

            query_embedding: List[float] = []
            if query:
                try:
                    query_embedding = list(encoder.encode(query) or [])
                except Exception:
                    query_embedding = []

            similarities: List[float] = []
            chunk_embeddings: List[dict] = []

            for raw_chunk in chunks:
                chunk = raw_chunk if isinstance(raw_chunk, dict) else {}
                body = self._evidence_body(chunk)

                try:
                    embedding = list(encoder.encode(body if body else " ") or [])
                except Exception:
                    embedding = []

                chunk_embeddings.append(
                    {
                        "chunk_id": str(chunk.get("chunk_id") or ""),
                        "source": str(chunk.get("source") or chunk.get("doc_id") or ""),
                        "embedding": embedding,
                    }
                )

                if body and query_embedding:
                    sim = self._cosine_similarity(embedding, query_embedding)
                    similarities.append(max(0.0, min(1.0, float(sim))))

            if not similarities:
                return 0.0, chunk_embeddings

            score = sum(similarities) / len(similarities)
            return max(0.0, min(1.0, float(score))), chunk_embeddings

    def _cosine_similarity(self, vec_a, vec_b) -> float:
            """计算两个向量的余弦相似度。"""
            if vec_a is None or vec_b is None:
                return 0.0

            try:
                a = [float(x) for x in list(vec_a)]
                b = [float(x) for x in list(vec_b)]
            except (TypeError, ValueError):
                return 0.0

            if not a or not b:
                return 0.0

            size = min(len(a), len(b))
            if size == 0:
                return 0.0

            dot = sum(a[i] * b[i] for i in range(size))
            norm_a = sum(a[i] * a[i] for i in range(size)) ** 0.5
            norm_b = sum(b[i] * b[i] for i in range(size)) ** 0.5

            if norm_a == 0.0 or norm_b == 0.0:
                return 0.0

            sim = dot / (norm_a * norm_b)
            return max(-1.0, min(1.0, sim))

    @property
    def short_term(self) -> List[dict]:
            """提供对短期记忆列表的访问（兼容规格中 self.short_term 的引用）。"""
            return self._short_term_memory

    def add_short_term(self, query: str, result: dict, session_id: str = None) -> None:
            """
            添加短期记忆。

            规格：
            1. 未传 session_id 时自动生成 UUID
            2. 记录 timestamp / access_count
            3. 基于 _evidence_chunks_from_result(result) 构造 chunks
            4. 调用 compute_memory_similarity(chunks_list, query)
            5. 若 result 含有 "score" 键，则 memory_item["score"] = computed_score；否则为 0.5
            6. 维护容量上限，超出时删除最旧记录
            """
            if session_id is None:
                session_id = str(uuid.uuid4())

            if result is None:
                result = {}

            timestamp = datetime.now()
            access_count = 0

            chunks_list = self._evidence_chunks_from_result(result)
            computed_score, embeddings = self.compute_memory_similarity(chunks_list, query)

            # 使用实际计算的相似度分数；计算失败（返回 0）时用 0.5 兜底
            score = computed_score if computed_score > 0 else 0.5

            normalized_embeddings = []
            for chunk, emb in zip(chunks_list, embeddings or []):
                if isinstance(emb, dict):
                    vector = emb.get("embedding") or []
                else:
                    vector = emb or []
                normalized_embeddings.append(
                    {
                        "chunk_id": chunk.get("chunk_id", ""),
                        "source": chunk.get("source", ""),
                        "embedding": vector,
                    }
                )

            memory_item = {
                "query": query,
                "result": result,
                "session_id": session_id,
                "timestamp": timestamp,
                "score": score,
                "access_count": access_count,
                "embeddings": normalized_embeddings,
            }

            self._short_term_memory.append(memory_item)

            while len(self._short_term_memory) > self._short_term_capacity:
                self._short_term_memory.pop(0)

    def update_access_count(self, memory_item: dict) -> None:
            """
            更新短期记忆访问次数。

            规则：
            - 若 memory_item 不存在 "access_count"，则初始化为 1
            - 若已存在，则累加 1
            - 最大值为 10；若已经达到或超过 10，则保持为 10
            """
            if not isinstance(memory_item, dict):
                return None

            max_access_count = 10

            if "access_count" not in memory_item:
                memory_item["access_count"] = 1
                return None

            current = memory_item.get("access_count")

            try:
                current_value = int(current)
            except (TypeError, ValueError):
                memory_item["access_count"] = 1
                return None

            if current_value >= max_access_count:
                memory_item["access_count"] = max_access_count
            else:
                memory_item["access_count"] = current_value + 1

            return None

    def compress_memory(self, result: dict) -> Tuple[str, List[float]]:
            """
            压缩记忆内容以及获得对应 embedding。

            规格：
            1. 尝试调用 LLM 生成自然语义文本摘要
            2. LLM 调用失败或超时时，使用 TextRank 生成摘要回退
            3. 将压缩文本生成 embedding 向量
            4. 返回压缩后的文本及 embedding

            Args:
                result: 记忆内容 dict

            Returns:
                (compressed_text, embedding)
            """
            if not isinstance(result, dict):
                result = {}

            chunks = self._evidence_chunks_from_result(result)
            if not chunks:
                encoder = self._get_encoder()
                try:
                    empty_embedding = list(encoder.encode(" ") or [])
                except Exception:
                    empty_embedding = [0.0] * 384
                return "", empty_embedding

            combined_text = "\n\n".join(
                c.get("text_snippet", "") for c in chunks if c.get("text_snippet")
            )
            if not combined_text.strip():
                encoder = self._get_encoder()
                try:
                    empty_embedding = list(encoder.encode(" ") or [])
                except Exception:
                    empty_embedding = [0.0] * 384
                return "", empty_embedding

            compressed_text = ""
            llm_success = False
            try:
                llm = self._get_llm()
                from src.libs.llm.base_llm import Message

                messages = [
                    Message(
                        role="system",
                        content=(
                            "你是一个记忆压缩助手。请将以下文本压缩为简洁的摘要，保留关键信息。"
                        ),
                    ),
                    Message(role="user", content=combined_text[:4000]),
                ]
                response = llm.chat(messages)
                if response and hasattr(response, "content"):
                    compressed_text = str(response.content or "").strip()
                    if compressed_text and not self._is_placeholder_llm_summary(
                        compressed_text
                    ):
                        llm_success = True
            except Exception:
                pass

            if not llm_success or not compressed_text:
                compressed_text = self._fallback_compress(combined_text)

            max_chars = self._compress_max_tokens * 4
            if len(compressed_text) > max_chars:
                compressed_text = compressed_text[:max_chars]

            encoder = self._get_encoder()
            try:
                embedding = list(
                    encoder.encode(compressed_text if compressed_text else " ") or []
                )
            except Exception:
                embedding = [0.0] * 384

            return compressed_text, embedding

    def _extract_sentences(self, text: str) -> List[str]:
            """
            简单句子分割（用于 TextRank 回退）。

            Args:
                text: 输入文本

            Returns:
                句子列表
            """
            import re

            if not text:
                return []

            # 简单按句号、问号、感叹号分割
            sentences = re.split(r'[。！？.!?]\s*', text)
            # 过滤空句子
            sentences = [s.strip() for s in sentences if s.strip()]
            return sentences

    def _is_placeholder_llm_summary(text: str) -> bool:
            """单测 stub LLM 等占位摘要，应走非 LLM 回退。"""
            normalized = (text or "").strip().lower()
            if not normalized:
                return True
            if normalized in {"stub summary", "stub"}:
                return True
            return normalized.startswith("stub ")

    def _fallback_compress(self, text: str) -> str:
            """
            非 LLM 回退压缩：提取前几句作为摘要。
            """
            if not text:
                return ""
            sentences = self._extract_sentences(text)
            if sentences:
                return " ".join(sentences[:5])
            # 直接截断
            max_chars = self._compress_max_tokens * 4
            return text[:max_chars] if len(text) > max_chars else text

    def _text_score_pairs_from_item(self, item: dict) -> List[Tuple[str, float]]:
            """从单条记忆条目或 get_relevant 结果中提取 (text, score)。"""
            score_raw = item.get("score")
            try:
                score = float(score_raw) if score_raw is not None else 0.5
            except (TypeError, ValueError):
                score = 0.5
            if "score" not in item:
                score = 0.5

            pairs: List[Tuple[str, float]] = []

            for chunk in self._evidence_chunks_from_result(item):
                body = chunk.get("text_snippet", "")
                if body:
                    pairs.append((body, score))

            if not pairs and "result" in item:
                inner = item.get("result")
                if isinstance(inner, dict):
                    for chunk in self._evidence_chunks_from_result(inner):
                        body = chunk.get("text_snippet", "")
                        if body:
                            pairs.append((body, score))

            if not pairs:
                body = self._evidence_body(item)
                if body:
                    pairs.append((body, score))

            if not pairs:
                text_val = str(item.get("text") or item.get("text_snippet") or "").strip()
                if text_val:
                    pairs.append((text_val, score))

            return pairs

    def compress_short_term(self, result: List[dict]) -> str:
            """
            压缩短期记忆内容为文本摘要。

            Args:
                result: List[dict], 记忆条目列表

            Returns:
                str: 压缩后的记忆文本
            """
            if not result or not isinstance(result, list):
                return ""

            text_score_pairs: List[Tuple[str, float]] = []
            for item in result:
                if not isinstance(item, dict):
                    continue
                text_score_pairs.extend(self._text_score_pairs_from_item(item))

            if not text_score_pairs:
                return ""

            combined_parts = [
                f"[score={score:.2f}] {text}" for text, score in text_score_pairs
            ]
            combined = "\n\n".join(combined_parts)

            compressed_text = ""
            llm_success = False
            try:
                llm = self._get_llm()
                from src.libs.llm.base_llm import Message

                messages = [
                    Message(
                        role="system",
                        content=(
                            "你是一个记忆压缩助手。请根据各段文本的 score（越高越重要）"
                            "生成一段精炼的上下文摘要，使其可直接与用户问题拼接使用。"
                            "突出高 score 的信息。"
                        ),
                    ),
                    Message(role="user", content=combined[:4000]),
                ]
                response = llm.chat(messages)
                if response and hasattr(response, "content"):
                    compressed_text = str(response.content or "").strip()
                    if compressed_text and not self._is_placeholder_llm_summary(
                        compressed_text
                    ):
                        llm_success = True
            except Exception:
                pass

            if not llm_success or not compressed_text:
                sorted_pairs = sorted(
                    text_score_pairs, key=lambda x: x[1], reverse=True
                )
                compressed_text = " ".join(text for text, _ in sorted_pairs)

            max_len = self._compress_max_tokens * 4
            if len(compressed_text) > max_len:
                compressed_text = compressed_text[:max_len]
            return compressed_text.strip()

    def condition_fn(self, memory_item: dict) -> bool:
            """
            判断短期记忆是否升级到长期记忆。

            综合 score = w_time * score_time + w_importance * score_importance + w_freq * score_freq
            若 >= threshold 则返回 True。
            """
            if not isinstance(memory_item, dict):
                return False

            import math

            max_hours = 24.0
            timestamp = memory_item.get("timestamp")
            if isinstance(timestamp, datetime):
                elapsed_hours = max(
                    0.0, (datetime.now() - timestamp).total_seconds() / 3600.0
                )
                score_time = max(0.0, 1.0 - elapsed_hours / max_hours)
            else:
                score_time = 0.0

            score_importance_raw = memory_item.get("score")
            try:
                score_importance = (
                    float(score_importance_raw)
                    if score_importance_raw is not None
                    else 0.0
                )
            except (TypeError, ValueError):
                score_importance = 0.0
            score_importance = max(0.0, min(1.0, score_importance))

            access_count_raw = memory_item.get("access_count")
            try:
                access_count = (
                    int(access_count_raw) if access_count_raw is not None else 0
                )
            except (TypeError, ValueError):
                access_count = 0
            access_count = max(0, access_count)
            score_freq = 1.0 - math.exp(-access_count)

            score_total = (
                self._w_time * score_time
                + self._w_importance * score_importance
                + self._w_freq * score_freq
            )

            return score_total >= self._threshold - 1e-9

    def delete_short_term(self, to_delete: list) -> None:
            """删除短期记忆列表中指定的 memory_item。"""
            if not to_delete:
                return
            self._short_term_memory = [
                item for item in self._short_term_memory if item not in to_delete
            ]

    def promote_to_long_term(self) -> None:
            """将符合条件的短期记忆升级到长期记忆。"""
            to_promote = [
                item for item in self._short_term_memory
                if self.condition_fn(item)
            ]

            if not to_promote:
                return

            for memory_item in to_promote:
                compressed_text, embedding = self.compress_memory(memory_item.get("result", {}))

                # 构建 chunks metadata
                raw_chunks = memory_item.get("result", {}).get("chunks")
                if raw_chunks and isinstance(raw_chunks, list):
                    chunks_meta = [
                        {
                            "source": str(c.get("source", "")),
                            "chunk_id": str(c.get("chunk_id", "")),
                            "page": c.get("page"),
                        }
                        for c in raw_chunks
                    ]
                else:
                    evidence = self._evidence_chunks_from_result(memory_item.get("result", {}))
                    chunks_meta = [
                        {
                            "source": str(c.get("source", "")),
                            "chunk_id": str(c.get("chunk_id", "")),
                            "page": None,
                        }
                        for c in evidence
                    ]

                metadata = {
                    "compressed_text": compressed_text,
                    "embedding": embedding,
                    "original_query": memory_item.get("query", ""),
                    "session_id": memory_item.get("session_id", ""),
                    "timestamp": datetime.now().isoformat(),
                    "score": memory_item.get("score", 0.5),
                    "access_count": memory_item.get("access_count", 0),
                    "chunks": chunks_meta,
                }

                # 写入 ChromaDB
                if self._long_term_collection is not None:
                    doc_id = str(uuid.uuid4())
                    try:
                        self._long_term_collection.add(
                            ids=[doc_id],
                            embeddings=[embedding],
                            metadatas=[{
                                "compressed_text": compressed_text,
                                "original_query": metadata["original_query"],
                                "session_id": metadata["session_id"],
                                "timestamp": metadata["timestamp"],
                                "score": metadata["score"],
                                "access_count": metadata["access_count"],
                            }],
                            documents=[compressed_text],
                        )
                    except Exception:
                        pass

                # 生成情景记忆
                try:
                    self.add_event(memory_item)
                except Exception as e:
                    import logging
                    logging.warning(f"add_event failed in promote_to_long_term: {e}")
                    import traceback
                    traceback.print_exc()

            self.delete_short_term(to_promote)

    def get_relevant(self, query: str) -> List[dict]:
        """Return top-k memory snippets with text and similarity score."""
        if not query or not str(query).strip():
            return []

        encoder = self._get_encoder()
        try:
            query_embedding = list(encoder.encode(str(query).strip()) or [])
        except Exception:
            query_embedding = []

        if not query_embedding:
            return []

        scored_items: List[dict] = []

        for memory_item in self._short_term_memory:
            embeddings_list = memory_item.get("embeddings") or []
            similarities: List[float] = []
            for emb_entry in embeddings_list:
                if isinstance(emb_entry, dict):
                    vec = emb_entry.get("embedding") or []
                else:
                    vec = emb_entry if isinstance(emb_entry, list) else []
                if vec:
                    sim = self._cosine_similarity(vec, query_embedding)
                    similarities.append(max(0.0, float(sim)))

            if similarities:
                item_score = max(similarities)
            else:
                try:
                    item_score = float(memory_item.get("score") or 0.0)
                except (TypeError, ValueError):
                    item_score = 0.0
                item_score = max(0.0, min(1.0, item_score))

            text_parts: List[str] = []
            for chunk in self._evidence_chunks_from_result(memory_item.get("result", {})):
                snippet = chunk.get("text_snippet", "")
                if snippet:
                    text_parts.append(snippet)
            if not text_parts:
                q = str(memory_item.get("query") or "").strip()
                if q:
                    text_parts.append(q)
            text = "\n".join(text_parts)
            if text:
                scored_items.append({"text": text, "score": item_score})
                self.update_access_count(memory_item)

        if self._long_term_collection is not None:
            try:
                if hasattr(self._long_term_collection, "query"):
                    raw = self._long_term_collection.query(
                        query_embeddings=[query_embedding],
                        n_results=max(self._top_k_long, 1),
                    )
                    distances = (raw or {}).get("distances") or [[]]
                    documents = (raw or {}).get("documents") or [[]]
                    metadatas = (raw or {}).get("metadatas") or [[]]
                    for dist_row, doc_row, meta_row in zip(
                        distances, documents, metadatas
                    ):
                        for dist, doc, meta in zip(
                            dist_row or [], doc_row or [], meta_row or []
                        ):
                            try:
                                sim = 1.0 - float(dist)
                            except (TypeError, ValueError):
                                sim = 0.0
                            sim = max(0.0, min(1.0, sim))
                            meta = meta if isinstance(meta, dict) else {}
                            lt_text = str(
                                doc or meta.get("compressed_text") or ""
                            ).strip()
                            if lt_text:
                                scored_items.append({"text": lt_text, "score": sim})
            except Exception:
                pass

        scored_items.sort(key=lambda x: x["score"], reverse=True)
        top_k = self._top_k_short + self._top_k_long
        return scored_items[:top_k]


    def _ensure_episodic_table(self) -> None:
        if self.sqlite_conn is None:
            return
        self.sqlite_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodic_events (
                event_id TEXT PRIMARY KEY,
                event_text TEXT,
                timestamp TEXT,
                session_id TEXT,
                related_chunks TEXT
            )
            """
        )

    def _build_qdrant_episodic_filter(self, session_id: str) -> dict:
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        return {
            "must": [
                {"key": "session_id", "match": {"value": session_id}},
                {"key": "timestamp", "range": {"gte": seven_days_ago}},
            ]
        }

    def retrieve_context(self, query: str, session_id: str | None = None) -> str:
        """检索相关记忆上下文（短期 + 长期 + 情景记忆）"""
        if query is None or not str(query).strip():
            return ""

        parts = []

        # 1. 短期 + 长期记忆（混合在一起）
        relevant = self.get_relevant(str(query).strip())
        if relevant:
            memory_text = self.compress_short_term(relevant)
            if memory_text:
                parts.append(f"## 记忆检索（短期+长期）\n{memory_text}")

        # 2. 情景记忆（如果配置了 Qdrant/SQLite）
        if self.sqlite_conn is not None or self.qdrant_collection is not None:
            try:
                episodic_text = self.query_relevant_events(str(query).strip(), session_id or "")
                if episodic_text and str(episodic_text).strip():
                    parts.append(f"## 情景记忆\n{episodic_text}")
            except Exception:
                pass  # 静默失败，不影响主流程

        return "\n\n".join(parts)

    def add_event(self, memory_item: dict) -> None:
        if not isinstance(memory_item, dict):
            return
        if self.sqlite_conn is None and self.qdrant_collection is None:
            return

        query = str(memory_item.get("query") or "")
        result = memory_item.get("result") if isinstance(memory_item.get("result"), dict) else {}
        session_id = str(memory_item.get("session_id") or "")
        timestamp = memory_item.get("timestamp")
        if isinstance(timestamp, datetime):
            ts_str = timestamp.isoformat()
        else:
            ts_str = datetime.now().isoformat()

        evidence_parts = [
            c.get("text_snippet", "")
            for c in self._evidence_chunks_from_result(result)
            if c.get("text_snippet")
        ]
        evidence_text = "\n".join(evidence_parts)
        if not evidence_text:
            evidence_text = str(result.get("text") or "").strip()

        score = memory_item.get("score", 0.5)
        user_content = f"{query}\n{evidence_text}\nscore: {score}"

        event_text = ""
        llm_ok = False
        try:
            llm = self._get_llm()
            from src.libs.llm.base_llm import Message

            messages = [
                Message(
                    role="system",
                    content="你是情景记忆生成助手。请根据用户问题与证据生成简洁的事件描述。",
                ),
                Message(role="user", content=user_content[:4000]),
            ]
            response = llm.chat(messages)
            if response and hasattr(response, "content"):
                event_text = str(response.content or "").strip()
                if event_text and not self._is_placeholder_llm_summary(event_text):
                    llm_ok = True
        except Exception:
            pass

        if not llm_ok or not event_text:
            event_text = f"{query}: {evidence_text}".strip() if evidence_text else query

        encoder = self._get_encoder()
        try:
            embedding = list(encoder.encode(event_text if event_text else " ") or [])
        except Exception:
            embedding = [0.0] * 384

        related_chunks = [
            {
                "chunk_id": c.get("chunk_id", ""),
                "source": c.get("source", ""),
                "text_snippet": c.get("text_snippet", ""),
            }
            for c in self._evidence_chunks_from_result(result)
        ]
        related_json = json.dumps(related_chunks, ensure_ascii=False)

        event_id = str(uuid.uuid4())

        if self.sqlite_conn is not None:
            self._ensure_episodic_table()
            self.sqlite_conn.execute(
                "INSERT INTO episodic_events "
                "(event_id, event_text, timestamp, session_id, related_chunks) "
                "VALUES (?,?,?,?,?)",
                (event_id, event_text, ts_str, session_id, related_json),
            )
            self.sqlite_conn.commit()

        if self.qdrant_collection is not None:
            payload = {
                "event_id": event_id,
                "session_id": session_id,
                "timestamp": ts_str,
            }
            point = {"id": event_id, "vector": embedding, "payload": payload}
            try:
                if hasattr(self.qdrant_collection, "upsert"):
                    self.qdrant_collection.upsert(points=[point])
                elif hasattr(self.qdrant_collection, "add"):
                    self.qdrant_collection.add(points=[point])
            except TypeError:
                try:
                    self.qdrant_collection.upsert(
                        collection_name="episodic", points=[point]
                    )
                except Exception:
                    pass
            except Exception:
                pass

    def query_relevant_events(self, query: str, session_id: str) -> str:
            """
            返回与 query 最相关的情景记忆文本，仅限当前 session 且最近 7 天。

            1. 使用 DenseEncoder 对 query 编码。
            2. 在 Qdrant collection 中搜索 top‑k 相似 embedding，过滤：
               - session_id == 给定值
               - timestamp 在最近 7 天内
            3. 候选不足 k 时使用全部命中的 event。
            4. 对每个命中 event_id 从 SQLite 取出 event_text。
            5. 将所有 event_text 拼接为单个字符串返回；若无则返回 ""。
            """
            if self.sqlite_conn is None or self.qdrant_collection is None:
                return ""

            encoder = self._get_encoder()
            query_vec = encoder.encode(query)
            if not query_vec:
                return ""

            now = datetime.now()
            seven_days_ago = now - timedelta(days=7)

            # Qdrant payload 过滤器
            filter_dict = {
                "must": [
                    {"key": "session_id", "match": {"value": session_id}},
                    {"key": "timestamp", "range": {
                        "gte": seven_days_ago.isoformat(),
                        "lte": now.isoformat()
                    }}
                ]
            }

            try:
                search_result = self.qdrant_collection.search(
                    query_vector=query_vec,
                    limit=self._top_k_episodic,
                    query_filter=filter_dict
                )
            except Exception:
                search_result = []

            event_ids = []
            for hit in search_result:
                hit_id = hit.id if hasattr(hit, "id") else None
                if hit_id is not None:
                    event_ids.append(hit_id)

            if not event_ids:
                return ""

            texts: list[str] = []
            cursor = self.sqlite_conn.cursor()
            for eid in event_ids:
                try:
                    cursor.execute(
                        "SELECT event_text FROM episodic_events WHERE event_id = ?",
                        (str(eid),)
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        texts.append(str(row[0]))
                except Exception:
                    continue

            return "\n".join(texts)
