"""Query Processor for preprocessing user queries.

This module provides query preprocessing functionality including:
- Keyword extraction using rule-based tokenization
- Stopword filtering for Chinese and English
- Filter parsing from query syntax (e.g., "collection:docs")
- Query normalization and cleaning

Design Principles:
- Rule-based first: Use simple, deterministic rules for reliability
- Language-aware: Support both Chinese and English queries
- Extensible: Easy to add synonym expansion or LLM-based processing later
- Configuration-driven: Stopwords and patterns configurable via settings
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Pattern, Set

import jieba

from src.core.types import ProcessedQuery

import json
import logging

from src.libs.llm.llm_factory import LLMFactory
from src.libs.llm.base_llm import Message

from pathlib import Path
from src.core.settings import resolve_path

logger = logging.getLogger(__name__)


# Default stopwords for Chinese 中文停用词集合
CHINESE_STOPWORDS: Set[str] = {
    # 疑问词
    "如何", "怎么", "怎样", "什么", "哪个", "哪些", "为什么", "为何",
    "谁", "多少", "几", "是否", "能否", "可否",
    # 助词
    "的", "地", "得", "了", "着", "过", "吗", "呢", "吧", "啊", "呀",
    # 介词/连词
    "在", "于", "和", "与", "或", "及", "并", "而", "但", "但是",
    "因为", "所以", "如果", "那么", "虽然", "然而",
    # 代词
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那",
    "这个", "那个", "这些", "那些", "这里", "那里",
    # 副词
    "很", "非常", "特别", "更", "最", "都", "也", "还", "又", "再",
    "已", "已经", "正在", "将", "会", "能", "可以", "应该", "必须",
    # 动词(通用)
    "是", "有", "做", "进行", "使用", "通过",
    # 量词
    "个", "种", "类",
    # 标点等
    "？", "。", "！", "，", "、",
}

# Default stopwords for English 英文停用词集合
ENGLISH_STOPWORDS: Set[str] = {
    # Articles
    "a", "an", "the",
    # Prepositions
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "about", "through", "between", "after", "before",
    # Conjunctions
    "and", "or", "but", "if", "then", "because", "while", "although",
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they", "this", "that",
    "these", "those", "what", "which", "who", "whom", "whose",
    # Auxiliary verbs
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "can",
    # Common verbs
    "get", "use", "make",
    # Question words
    "how", "why", "when", "where",
    # Others
    "not", "no", "yes", "so", "very", "just", "also", "too",
}

# Combined default stopwords
DEFAULT_STOPWORDS: Set[str] = CHINESE_STOPWORDS | ENGLISH_STOPWORDS

# Pattern for filter syntax: key:value 用来匹配这种 key:value 的过滤语法。
FILTER_PATTERN: Pattern = re.compile(r'(\w+):([^\s]+)')


@dataclass
class QueryProcessorConfig:
    """Configuration for QueryProcessor.
    给 QueryProcessor 提供配置参数
    Attributes:
        stopwords: Set of words to filter out
        min_keyword_length: Minimum length for a keyword to be included
        max_keywords: Maximum number of keywords to extract
        enable_filter_parsing: Whether to parse filter syntax from query
    """
    stopwords: Set[str] = field(default_factory=lambda: DEFAULT_STOPWORDS.copy())
    min_keyword_length: int = 1
    max_keywords: int = 20
    enable_filter_parsing: bool = True
    enable_mqe: bool = True
    enable_hyde: bool = True
    max_expanded_queries: int = 4
    llm_timeout_fallback: bool = True


class QueryProcessor:
    """Preprocesses user queries for retrieval.
    
    Extracts keywords, filters stopwords, and parses filter syntax
    to prepare queries for Dense and Sparse retrievers.
    
    Example:
        >>> processor = QueryProcessor()
        >>> result = processor.process("如何配置 Azure OpenAI？")
        >>> print(result.keywords)
        ['配置', 'Azure', 'OpenAI']
    """
    
    def __init__(
        self,
        config: Optional[QueryProcessorConfig] = None,
        settings: Optional[Any] = None,
        llm: Optional[Any] = None,
        prompt_path: Optional[str] = None,
    ):
        self.config = config or QueryProcessorConfig()
        self.settings = settings
        self._llm = llm
        self._expansion_cache: Dict[str, Dict[str, Any]] = {} #生成query的cache
        self.prompt_path = prompt_path or str(
            resolve_path("config/prompts/query_expansion.txt")
        )
        try:
            self.prompt_template = self._load_prompt_template(self.prompt_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load query expansion prompt: {e}") from e
        if self.settings and hasattr(self.settings, "query_expansion"):
            qe = self.settings.query_expansion
            self.config.enable_mqe = qe.get("enable_mqe", True)
            self.config.enable_hyde = qe.get("enable_hyde", True)
            self.config.max_expanded_queries = qe.get("max_expanded_queries", 4)

    def _load_prompt_template(self, path: str) -> str:
        prompt_file = Path(path)
        if not prompt_file.exists():
            raise FileNotFoundError(f"Query expansion prompt file not found: {path}")
        return prompt_file.read_text(encoding="utf-8")
    
    def process(self, query: str) -> ProcessedQuery:
        """Process a user query into structured format.
        把原始 query 处理成结构化结果
        Args:
            query: Raw user query string
            
        Returns:
            ProcessedQuery with extracted keywords and filters
        """
        if not query or not query.strip():
            return ProcessedQuery(
                original_query=query or "",
                keywords=[],
                filters={}
            )
        
        # Normalize query
        normalized = self._normalize(query)
        
        # Extract filters from query (e.g., "collection:docs")
        filters, query_without_filters = self._extract_filters(normalized)
        
        # Tokenize and extract keywords
        tokens = self._tokenize(query_without_filters)
        
        # Filter stopwords and apply constraints
        keywords = self._filter_keywords(tokens)
        
        expanded_queries, hyde_passage = self._build_expanded_queries(
            query_without_filters=query_without_filters,
            keywords=keywords,
        )

        return ProcessedQuery(
            original_query=query,
            keywords=keywords,
            filters=filters,
            expanded_terms=expanded_queries,
            hyde_passage=hyde_passage,
        )
    
    def _normalize(self, query: str) -> str:
        """Normalize query string.
        规范化 query：去掉首尾和中间多余空白；把连续空格压成一个空格
        - Strip whitespace
        - Normalize unicode
        - Convert to consistent format
        
        Args:
            query: Raw query string
            
        Returns:
            Normalized query string
        """
        # Strip and normalize whitespace
        normalized = " ".join(query.split())
        return normalized
    
    def _extract_filters(self, query: str) -> tuple[Dict[str, Any], str]:
        """Extract filter syntax from query.
        从 query 里提取 key:value 形式的过滤条件，并返回：过滤条件字典，去掉过滤条件后的纯文本 query
        Supports syntax like: "collection:api-docs keyword1 keyword2"
        
        Args:
            query: Normalized query string
            
        Returns:
            Tuple of (filters dict, query without filter syntax)
        """
        if not self.config.enable_filter_parsing:
            return {}, query
        
        filters: Dict[str, Any] = {}
        
        # Find all filter patterns
        matches = FILTER_PATTERN.findall(query)
        for key, value in matches:
            # Support common filter keys
            key_lower = key.lower()
            if key_lower in ("collection", "col", "c"):
                filters["collection"] = value
            elif key_lower in ("type", "doc_type", "t"):
                filters["doc_type"] = value
            elif key_lower in ("source", "src", "s"):
                filters["source_path"] = value
            elif key_lower in ("tag", "tags"):
                # Tags can be comma-separated 如果不是上面这些已知 key，就按原样放入字典
                if "tags" not in filters:
                    filters["tags"] = []
                filters["tags"].extend(value.split(","))
            else:
                # Generic filter
                filters[key] = value
        
        # Remove filter patterns from query
        query_without_filters = FILTER_PATTERN.sub("", query).strip()
        query_without_filters = " ".join(query_without_filters.split())
        
        return filters, query_without_filters
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words/terms.
        把文本分成 token 列表。jieba
        Uses jieba for Chinese text segmentation, consistent with the
        index-side tokenizer (SparseEncoder) so BM25 matching works.
        English text is handled natively by jieba (preserved as-is).
        
        Args:
            text: Text to tokenize
            
        Returns:
            List of tokens
        """
        tokens: List[str] = []

        # Use jieba to segment (handles Chinese + keeps English intact)
        raw_tokens = jieba.lcut(text)

        for token in raw_tokens:
            token = token.strip()
            if not token:
                continue
            # Skip pure punctuation / whitespace
            if re.fullmatch(r'[\s\W]+', token, re.UNICODE):
                continue
            tokens.append(token)
        
        return tokens
    
    def _filter_keywords(self, tokens: List[str]) -> List[str]:
        """Filter tokens to get meaningful keywords.
        把分词结果进一步过滤，留下真正有意义的关键词。
        - Remove stopwords
        - Apply minimum length constraint
        - Deduplicate while preserving order
        - Apply maximum count limit
        
        Args:
            tokens: List of tokens
            
        Returns:
            List of filtered keywords
        """
        seen: Set[str] = set()
        keywords: List[str] = []
        
        for token in tokens:
            # Normalize for comparison
            token_lower = token.lower()
            
            # Skip if already seen (case-insensitive dedup) 去重
            if token_lower in seen:
                continue
            
            # Skip stopwords (check both original and lowercase) 去停用词
            if token in self.config.stopwords or token_lower in self.config.stopwords:
                continue
            
            # Skip if too short 去掉太短的 token
            if len(token) < self.config.min_keyword_length:
                continue
            
            # Add keyword (preserve original case)
            seen.add(token_lower)
            keywords.append(token)
            
            # Stop if we have enough 限制最大关键词数量
            if len(keywords) >= self.config.max_keywords:
                break
        
        return keywords
    
    def _get_llm(self) -> Optional[Any]:
        """Lazy-create LLM client for MQE / HyDE."""
        if self._llm is not None:
            return self._llm

        try:
            if self.settings is None:
                from src.core.settings import load_settings
                self.settings = load_settings()

            self._llm = LLMFactory.create(self.settings)
            return self._llm
        except Exception as exc:
            logger.warning("LLM unavailable for query expansion; fallback disabled: %s", exc)
            return None


    def _build_expanded_queries(
        self,
        query_without_filters: str,
        keywords: List[str],
    ) -> tuple[List[str], Optional[str]]:
        """Build LLM-based MQE queries and HyDE passage separately.

        MQE will be used by both dense and sparse retrieval.
        HyDE will be used only by dense retrieval.
        """
        if not self.config.enable_mqe and not self.config.enable_hyde:
            return [], None

        llm_result = self._llm_expand_query(
            query=query_without_filters,
            keywords=keywords,
        )

        seen = {query_without_filters.strip().lower()}
        mqe_queries: List[str] = []

        def normalize_item(item: str) -> Optional[str]:
            item = " ".join(str(item).split())
            if not item:
                return None
            key = item.lower()
            if key in seen:
                return None
            seen.add(key)
            return item

        if self.config.enable_mqe:
            raw_mqe = llm_result.get("mqe_queries", [])
            if isinstance(raw_mqe, list):
                for q in raw_mqe:
                    # -1 是因为原 query 已经占一个位置
                    if len(mqe_queries) >= self.config.max_expanded_queries - 1:
                        break
                    item = normalize_item(q)
                    if item:
                        mqe_queries.append(item)

        hyde_passage: Optional[str] = None
        if self.config.enable_hyde:
            raw_hyde = llm_result.get("hyde_passage", "")
            if isinstance(raw_hyde, str) and raw_hyde.strip():
                hyde_passage = " ".join(raw_hyde.split())

        return mqe_queries, hyde_passage


    def _llm_expand_query(self, query: str, keywords: list[str]) -> dict[str, str | list[str]]:
        """
        Use LLM to generate MQE queries and a HyDE passage with cache and robust parsing.
        
        Args:
            query: Original user query.
            keywords: List of extracted keywords.
        
        Returns:
            dict with keys:
                - "mqe_queries": List[str]
                - "hyde_passage": str
        """
        import json, re

        # 生成缓存 key
        cache_key = f"{query.strip()}||{','.join(keywords)}"
        if not hasattr(self, "_expansion_cache"):
            self._expansion_cache: dict[str, dict] = {}

        if cache_key in self._expansion_cache:
            logger.debug("[MQE/HyDE] cache hit: %s", query[:80])
            return self._expansion_cache[cache_key]

        # 获取 LLM 实例
        llm = self._get_llm()
        if llm is None:
            result = {"mqe_queries": [], "hyde_passage": ""}
            self._expansion_cache[cache_key] = result
            return result

        # system + user 消息
        system_prompt = """
        You are a search query expansion module for an academic RAG system.
        Given a user question and keywords, generate retrieval queries that help find evidence in academic papers.
        Do NOT answer the question.

        Instructions:
        1. Generate 2–3 concise English retrieval queries (mqe_queries)
        - Use academic-paper wording
        - Include entities, methods, datasets, metrics if relevant
        - No explanations

        2. Generate one short hypothetical evidence passage (hyde_passage)
        - It should look like a paragraph in an academic paper
        - Should help semantic retrieval
        - Do not hallucinate specific numbers

        Return ONLY valid JSON
        """.strip()

        user_prompt = f"""
        User question:
        {query}

        Extracted keywords:
        {', '.join(keywords)}
        """.strip()

        try:
            logger.debug("[MQE/HyDE] sending query to LLM...")
            logger.debug("Query: %s", query)
            logger.debug("Keywords: %s", keywords)

            response = llm.chat(
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ],
                temperature=0.0,
                max_tokens=500,
            )

            logger.debug("[MQE/HyDE] raw response: %s", repr(response.content))

            # 调用稳健 parser
            result = self._parse_llm_expansion(response.content)

            # 存入 cache
            self._expansion_cache[cache_key] = result

            return result

        except Exception as exc:
            logger.warning("[MQE/HyDE] LLM query expansion failed: %s", exc)
            result = {"mqe_queries": [], "hyde_passage": ""}
            self._expansion_cache[cache_key] = result
            return result


    def _parse_llm_expansion(self, text: str) -> dict[str, str | list[str]]:
        """
        Robustly parse LLM JSON output, handling code fences, whitespace, list/dict.

        Returns:
            dict with keys "mqe_queries" (list) and "hyde_passage" (str)
        """
        import re, json

        text = (text or "").strip()

        # 去掉 ```json ``` 包裹
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except Exception:
            # 尝试匹配第一个 JSON 对象
            match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
            if not match:
                return {"mqe_queries": [], "hyde_passage": ""}
            try:
                data = json.loads(match.group(0))
            except Exception:
                return {"mqe_queries": [], "hyde_passage": ""}

        # 如果是 list，取第一个元素
        if isinstance(data, list):
            data = data[0] if data else {}

        if not isinstance(data, dict):
            return {"mqe_queries": [], "hyde_passage": ""}

        # MQE
        mqe_queries = data.get("mqe_queries", [])
        if not isinstance(mqe_queries, list):
            mqe_queries = []
        mqe_queries = [str(q).strip() for q in mqe_queries if isinstance(q, str) and q.strip()]

        # HyDE
        hyde_passage = data.get("hyde_passage", "")
        if not isinstance(hyde_passage, str):
            hyde_passage = ""

        return {"mqe_queries": mqe_queries, "hyde_passage": hyde_passage.strip()}


    
    
    def add_stopwords(self, words: Set[str]) -> None:
        """Add words to stopword set.
        往当前停用词集合里新增停用词
        Args:
            words: Set of words to add
        """
        self.config.stopwords.update(words)
    
    def remove_stopwords(self, words: Set[str]) -> None:
        """Remove words from stopword set.
        从当前停用词集合里移除一些词。
        Args:
            words: Set of words to remove
        """
        self.config.stopwords -= words


def create_query_processor(
    stopwords: Optional[Set[str]] = None,
    min_keyword_length: int = 1,
    max_keywords: int = 20,
    enable_filter_parsing: bool = True,
    enable_mqe: bool = True,
    enable_hyde: bool = True,
    max_expanded_queries: int = 4,
) -> QueryProcessor:
    """Factory function to create QueryProcessor.
    这是一个工厂函数。根据你传入的参数，先创建 QueryProcessorConfig，再创建 QueryProcessor 实例并返回。
    Args:
        stopwords: Custom stopwords set. Uses default if None.
        min_keyword_length: Minimum keyword length
        max_keywords: Maximum keywords to extract
        enable_filter_parsing: Whether to parse filter syntax
        
    Returns:
        Configured QueryProcessor instance
    """
    config = QueryProcessorConfig(
        stopwords=stopwords if stopwords is not None else DEFAULT_STOPWORDS.copy(),
        min_keyword_length=min_keyword_length,
        max_keywords=max_keywords,
        enable_filter_parsing=enable_filter_parsing,
        enable_mqe=enable_mqe,
        enable_hyde=enable_hyde,
        max_expanded_queries=max_expanded_queries,
    )
    return QueryProcessor(config)
