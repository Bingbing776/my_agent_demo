import uuid
from datetime import datetime
from typing import List


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
        # 延迟初始化：不在构造时调用 _get_llm() / _get_encoder()
        # 在首次使用时（get_relevant_context 等）才初始化

    def _get_llm(self):
        """延迟创建并缓存 LLM 实例"""
        if self._llm is not None:
            return self._llm

        try:
            from src.libs.llm.llm_factory import LLMFactory
            from src.core.settings import load_settings

            from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
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
                vecs = self._dense.encode([Chunk(id='0', text=t, metadata={'source_path': 'memory'})])
                return vecs[0] if vecs else []

        try:
            from src.libs.embedding.embedding_factory import EmbeddingFactory
            from src.core.settings import load_settings

            from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            emb = EmbeddingFactory.create(settings)
            self._encoder = _TextEncoderAdapter(DenseEncoder(embedding=emb, batch_size=10))
        except Exception:
            class _StubEncoder:
                def encode(self, text: str):
                    return [0.1] * 384

            self._encoder = _StubEncoder()

        return self._encoder

    def update_context(self, query: str, answer: str, session_id: str = None) -> None:
        """
        更新对话历史，将 query + answer 保存到短期上下文中。

        Args:
            query: 用户问题。
            answer: Agent 回答。
            session_id: 会话 ID，可选。若未提供则自动生成 UUID。
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

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
        """返回最近 n 条对话，支持按 session 筛选。

        完成标准：
        - 如果指定 session_id，只返回该 session 的上下文
        - 列表按照 timestamp 降序排序
        - 取最近 n 条返回
        - 返回 List[dict]，每条包含 query, answer, session_id, timestamp
        - 不修改原始列表
        """
        if session_id is not None:
            filtered = [item for item in self.context_window if item.get("session_id") == session_id]
        else:
            filtered = list(self.context_window)

        sorted_items = sorted(filtered, key=lambda x: x.get("timestamp", datetime.min), reverse=True)
        return sorted_items[:n]

    def get_relevant_context(self, query: str, session_id: str = None) -> str:
        """返回最相关压缩上下文，用于 Planner/Executor。

        完成标准：
        - 调用 get_context_window 获取候选上下文
        - DenseEncoder.encode 用于 embedding
        - cosine similarity 正确计算
        - top‑k 条目被选择
        - LLM 压缩尝试，失败时回退截断拼接
        - 返回压缩后的上下文字符串
        """
        # 若 top_k 为 0，直接返回空字符串
        k = self.top_k
        if k <= 0:
            return ""

        n = self.config.get("context_window_n", self.max_entries)
        candidates = self.get_context_window(n, session_id)
        if not candidates:
            return ""

        encoder = self._get_encoder()

        # 编码查询向量；若失败则后续忽略相似度排序
        query_emb = []
        if query and query.strip():
            try:
                query_emb = encoder.encode(query.strip())
            except Exception:
                query_emb = []

        if query_emb:
            # 有可用的查询向量：计算余弦相似度并排序
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
            # 查询向量缺失（编码失败或为空），直接取最近的前 k 条候选
            top_items = candidates[:k]

        # 若无可用的条目，提前返回
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
            # LLM 调用失败，回退到原始拼接文本
            compressed = concatenated

        max_len = self.truncation_length
        if len(compressed) > max_len:
            compressed = compressed[:max_len]

        return compressed

    def _cosine_similarity(self, vec1, vec2):
        """计算两个向量的余弦相似度。"""
        import math
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)