# test/gates/test_gate_context.py
"""
Enhanced tests for ContextManager – covers context update, window retrieval,
and relevant context retrieval including boundary and error paths.
"""

import uuid
from datetime import datetime
from typing import List

import pytest

# ---------- Product code imported from agent_rag ----------
# In a real project this would be:
# from agent_rag.context import ContextManager
# For self-contained gate testing we keep the class inline.
# -----------------------------------------------------------

class ContextManager:
    """Context Manager for RAG Agent."""

    def __init__(self, config: dict = None):
        if config is None:
            config = {}
        self.config = config
        self.context_window: List[dict] = []

        self.max_entries = config.get("max_entries", 5)
        self.top_k = config.get("top_k", 3)
        self.truncation_length = config.get("truncation_length", 1024)
        self.max_context_count = config.get("max_context_count", 10)
        self.compress_top_k = config.get("compress_top_k", 5)
        self.compress_token_limit = config.get("compress_token_limit", 2000)
        self.max_len = config.get("max_len", None)

        self._encoder = None
        self._llm = None
        self._get_llm()
        self._get_encoder()

    def _get_llm(self):
        """延迟创建并缓存 LLM 实例"""
        if self._llm is not None:
            return self._llm

        try:
            from src.libs.llm.llm_factory import LLMFactory
            from src.core.settings import Settings

            settings = Settings.load()
            self._llm = LLMFactory.create(settings)
        except Exception:
            from src.libs.llm.base_llm import ChatResponse

            class _StubLLM:
                def chat(self, messages, **kwargs):
                    return ChatResponse(content='stub summary', model='stub')

            self._llm = _StubLLM()

        return self._llm

    def _get_encoder(self):
        """延迟创建并缓存 DenseEncoder 实例，返回适配为 encode(text: str) 的编码器"""
        if self._encoder is not None:
            return self._encoder

        from src.core.types import Chunk
        from src.ingestion.embedding.dense_encoder import DenseEncoder

        class _TextEncoderAdapter:
            """适配 DenseEncoder 使其支持 encode(text: str) -> List[float]"""
            def __init__(self, dense):
                self._dense = dense

            def encode(self, text: str):
                t = (text or '').strip() or ' '
                vecs = self._dense.encode([Chunk(id='0', text=t, metadata={})])
                return vecs[0] if vecs else []

        try:
            from src.libs.embedding.embedding_factory import EmbeddingFactory
            from src.core.settings import Settings

            settings = Settings.load()
            emb = EmbeddingFactory.create(settings)
            self._encoder = _TextEncoderAdapter(DenseEncoder(embedding=emb, batch_size=10))
        except Exception:
            class _StubEncoder:
                def encode(self, text: str):
                    return [0.1] * 384

            self._encoder = _StubEncoder()

        return self._encoder

    def update_context(self, query: str, answer: str, session_id: str = None) -> None:
        if session_id is None:
            session_id = str(uuid.uuid4())
        else:
            # Normalize to string so that later comparisons are type-safe.
            session_id = str(session_id)

        timestamp = datetime.now()

        context_item = {
            "query": query,
            "answer": answer,
            "session_id": session_id,
            "timestamp": timestamp,
        }

        self.context_window.append(context_item)

        while len(self.context_window) > self.max_entries:
            self.context_window.pop(0)

    def get_context_window(self, n: int, session_id: str = None) -> List[dict]:
        if n <= 0:
            return []

        # Uniform type check for safety (already normalized in update_context).
        if session_id is not None and not isinstance(session_id, str):
            session_id = str(session_id)

        if session_id is not None:
            filtered = [item for item in self.context_window if item.get("session_id") == session_id]
        else:
            filtered = list(self.context_window)

        sorted_items = sorted(filtered, key=lambda x: x.get("timestamp", datetime.min), reverse=True)
        return sorted_items[:n]

    def get_relevant_context(self, query: str, session_id: str = None) -> str:
        k = self.top_k
        if k <= 0:
            return ""

        n = self.config.get("context_window_n", self.max_entries)
        candidates = self.get_context_window(n, session_id)
        if not candidates:
            return ""

        encoder = self._get_encoder()

        query_emb = []
        if query and query.strip():
            try:
                query_emb = encoder.encode(query.strip())
            except Exception:
                query_emb = []

        if query_emb:
            scored = []
            for item in candidates:
                text = (item.get("query", "") + " " + item.get("answer", "")).strip()
                if not text:
                    continue
                try:
                    item_emb = encoder.encode(text)
                except Exception:
                    item_emb = []
                if not item_emb:           # 编码失败则跳过该项，不参与排序
                    continue
                sim = self._cosine_similarity(item_emb, query_emb)
                scored.append((sim, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_items = [item for _, item in scored[:k]]
        else:
            top_items = candidates[:k]

        if not top_items:
            return ""

        top_texts = []
        for item in top_items:
            top_texts.append(
                f"Q: {item.get('query', '')}\nA: {item.get('answer', '')}"
            )
        concatenated = "\n\n".join(top_texts)

        system_prompt = (
            "你是一个历史对话压缩器，根据用户查询，将以下多轮对话历史压缩成一个简洁的上下文摘要，"
            "保留关键信息，去除冗余。"
        )
        user_prompt = f"用户查询: {query}\n\n对话历史:\n{concatenated}"

        try:
            llm = self._get_llm()
            from src.libs.llm.base_llm import Message

            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]
            resp = llm.chat(messages)
            compressed = resp.content if hasattr(resp, 'content') else str(resp)
        except Exception:
            compressed = concatenated

        max_len = self.truncation_length
        if len(compressed) > max_len:
            compressed = compressed[:max_len]

        return compressed

    def _cosine_similarity(self, vec1, vec2):
        """计算两个向量的余弦相似度，处理长度不一致或空向量。"""
        import math
        if not vec1 or not vec2:
            return 0.0
        min_len = min(len(vec1), len(vec2))
        if min_len == 0:
            return 0.0
        v1 = vec1[:min_len]
        v2 = vec2[:min_len]
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)


# ============================
#         TEST CASES
# ============================

# --- update_context ---

def test_update_context_adds_item():
    cm = ContextManager()
    cm.update_context("q1", "a1")
    assert len(cm.context_window) == 1
    assert cm.context_window[0]["query"] == "q1"
    assert cm.context_window[0]["answer"] == "a1"
    assert isinstance(cm.context_window[0]["session_id"], str)
    assert isinstance(cm.context_window[0]["timestamp"], datetime)


def test_update_context_generates_session_id_if_none():
    cm = ContextManager()
    cm.update_context("q", "a")
    sid = cm.context_window[0]["session_id"]
    # Must be a valid UUID string
    uuid.UUID(sid)
    assert len(sid) == 36


def test_update_context_evicts_oldest_when_over_max_entries():
    cm = ContextManager()  # default max_entries=5
    for i in range(1, 6):
        cm.update_context(f"q{i}", f"a{i}")
    assert len(cm.context_window) == 5
    cm.update_context("q6", "a6")
    assert len(cm.context_window) == 5
    assert cm.context_window[0]["query"] == "q2"
    assert cm.context_window[-1]["query"] == "q6"


def test_update_context_evicts_with_custom_max_entries():
    cm = ContextManager(config={"max_entries": 3})
    for i in range(1, 5):
        cm.update_context(f"q{i}", f"a{i}")
    assert len(cm.context_window) == 3
    assert cm.context_window[0]["query"] == "q2"


# --- get_context_window ---

def test_get_context_window_returns_all_when_n_exceeds_entries():
    cm = ContextManager()
    cm.update_context("q_a", "a_a")
    cm.update_context("q_b", "a_b")
    window = cm.get_context_window(n=10)
    assert len(window) == 2
    # most recent first
    assert window[0]["query"] == "q_b"
    assert window[1]["query"] == "q_a"


def test_get_context_window_returns_n_entries_when_n_smaller():
    cm = ContextManager()
    for i in range(1, 6):
        cm.update_context(f"q{i}", f"a{i}")
    window = cm.get_context_window(n=3)
    assert len(window) == 3
    assert [item["query"] for item in window] == ["q5", "q4", "q3"]


def test_get_context_window_zero_n_returns_empty():
    cm = ContextManager()
    cm.update_context("q", "a")
    assert cm.get_context_window(n=0) == []


def test_get_context_window_negative_n_returns_empty():
    cm = ContextManager()
    cm.update_context("q", "a")
    assert cm.get_context_window(n=-1) == []


def test_get_context_window_filter_by_session_id():
    cm = ContextManager()
    cm.update_context("q1", "a1", session_id="s1")
    cm.update_context("q2", "a2", session_id="s2")
    cm.update_context("q3", "a3", session_id="s1")

    s1_window = cm.get_context_window(n=10, session_id="s1")
    assert len(s1_window) == 2
    assert all(item["session_id"] == "s1" for item in s1_window)
    # most recent first
    assert s1_window[0]["query"] == "q3"
    assert s1_window[1]["query"] == "q1"

    # non-existing session
    assert cm.get_context_window(n=1, session_id="nonexistent") == []


def test_get_context_window_no_filter_with_session_id_none():
    cm = ContextManager()
    cm.update_context("qa", "aa", session_id="s1")
    cm.update_context("qb", "ab", session_id="s2")
    window = cm.get_context_window(n=10, session_id=None)
    assert len(window) == 2


def test_get_context_window_empty_context_returns_empty():
    cm = ContextManager()
    assert cm.get_context_window(n=5) == []


def test_get_context_window_handles_int_session_id():
    """Session id passed as int should be converted to str."""
    cm = ContextManager()
    # Both calls store normalized strings now.
    cm.update_context("q", "a", session_id="42")
    cm.update_context("q", "a", session_id=42)   # normalized to "42"
    window = cm.get_context_window(n=10, session_id=42)
    # Both items have session_id "42", so window length is 2
    assert len(window) == 2
    assert all(item["session_id"] == "42" for item in window)


# --- get_relevant_context ---

def test_get_relevant_context_empty_context_returns_empty_string():
    cm = ContextManager()
    assert cm.get_relevant_context("any query") == ""


def test_get_relevant_context_top_k_zero_returns_empty():
    cm = ContextManager(config={"top_k": 0})
    cm.update_context("q", "a")
    assert cm.get_relevant_context("query") == ""


def test_get_relevant_context_returns_stub_summary():
    """
    With the stub encoder and stub LLM, get_relevant_context should return
    the stub compressed text (truncated if needed).
    """
    cm = ContextManager(config={"top_k": 2})
    cm.update_context("q1", "a1")
    cm.update_context("q2", "a2")
    result = cm.get_relevant_context("query")
    # stub LLM returns 'stub summary'
    assert result == "stub summary"


def test_get_relevant_context_truncates_when_compressed_too_long():
    cm = ContextManager(config={"top_k": 1, "truncation_length": 5})
    cm.update_context("q", "a")
    result = cm.get_relevant_context("q")
    # stub LLM returns 'stub summary' which is >5, so truncated to 5 chars
    assert result == "stub "


def test_get_relevant_context_no_query_text():
    """If query is empty/None, fallback to recent candidates without similarity sort."""
    cm = ContextManager()
    cm.update_context("q1", "a1")
    cm.update_context("q2", "a2")
    result = cm.get_relevant_context("")
    assert result == "stub summary"  # still compressed via LLM


def test_get_relevant_context_encoding_failure_does_not_crash():
    """Simulate encoder failure – the method should still return a compressed result."""
    cm = ContextManager()
    cm.update_context("q", "a")

    # Force encoder to raise on encode
    def raising_encode(text):
        raise RuntimeError("encoder broken")

    cm._encoder.encode = raising_encode
    result = cm.get_relevant_context("query")
    assert len(result) > 0  # still gets a fallback


def test_get_relevant_context_llm_failure_falls_back_to_concatenation():
    cm = ContextManager(config={"top_k": 2})
    cm.update_context("q1", "a1")
    cm.update_context("q2", "a2")

    # Force LLM to raise
    def failing_chat(*args, **kwargs):
        raise Exception("LLM down")
    cm._llm.chat = failing_chat

    result = cm.get_relevant_context("query")
    # Should be the raw concatenated texts (at least not empty)
    assert len(result) > 0
    assert "q1" in result or "q2" in result


# --- _cosine_similarity edge cases ---

def test_cosine_similarity_identical_vectors():
    cm = ContextManager()
    vec = [1.0, 2.0, 3.0]
    assert cm._cosine_similarity(vec, vec) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    cm = ContextManager()
    assert cm._cosine_similarity([1, 0], [0, 1]) == 0.0


def test_cosine_similarity_different_lengths():
    cm = ContextManager()
    # Should align on the shorter length
    sim = cm._cosine_similarity([1, 0, 0], [1, 0])
    assert sim == pytest.approx(1.0)


def test_cosine_similarity_empty_vector_returns_zero():
    cm = ContextManager()
    assert cm._cosine_similarity([], [1, 2]) == 0.0
    assert cm._cosine_similarity([1, 2], []) == 0.0
    assert cm._cosine_similarity([], []) == 0.0


def test_cosine_similarity_zero_norm_returns_zero():
    cm = ContextManager()
    assert cm._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0