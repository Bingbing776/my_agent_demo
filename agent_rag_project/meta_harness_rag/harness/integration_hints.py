"""Harness Generator/Planner/Evaluator 共用：MODULAR 跨项目集成实现参考（注入 prompt，非产品代码）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

KNOWN_HELPER_SYMBOLS: tuple[str, ...] = (
    "_get_encoder",
    "_get_llm",
    "_cosine_similarity",
    "_evidence_body",
    "_evidence_chunks_from_result",
    "_normalize_call_tool_result",
    "_collect_images_from_raw",
    "summarize_mcp_result",
)


@dataclass(frozen=True)
class IntegrationHintSpec:
    hint_id: str
    symbols: frozenset[str]
    issue_patterns: tuple[re.Pattern[str], ...]
    target_file_markers: tuple[str, ...]
    build: Callable[[str, list[str]], str]


def related_symbols_from_issues(issues: str, primary: str) -> list[str]:
    """从 pytest 栈/issues 推断同文件还需修改的 def 名。"""
    found: list[str] = []
    for m in re.finditer(r"def\s+(_?\w+)|self\.(_?\w+)\(", issues or ""):
        name = m.group(1) or m.group(2)
        if name and name not in found and name != primary:
            found.append(name)
    for kw in KNOWN_HELPER_SYMBOLS:
        if kw in (issues or "") and kw not in found and kw != primary:
            found.append(kw)
    return found


def _matches(
    spec: IntegrationHintSpec,
    *,
    symbol: str,
    issues: str,
    target_file: str,
) -> bool:
    if symbol in spec.symbols:
        return True
    text = issues or ""
    if any(p.search(text) for p in spec.issue_patterns):
        return True
    tf = (target_file or "").replace("\\", "/").lower()
    if not tf:
        return False
    if not any(m.lower() in tf for m in spec.target_file_markers):
        return False
    if any(p.search(text) for p in spec.issue_patterns):
        return True
    if symbol in ("__init__", "call_tool", "execute_task", "fill_arguments", "plan", "evaluate"):
        return True
    return False


def _build_encoder_hint(primary_symbol: str, related: list[str]) -> str:
    extra = ""
    if related:
        extra = f"本轮 issues 还涉及: {', '.join(related)} — 与 `{primary_symbol}` 放在同一 ```python 块内。\n\n"
    return (
        "=== DenseEncoder / _get_encoder（tech_doc §1/§2）===\n"
        f"{extra}"
        "要点：\n"
        "1. 构造：DenseEncoder(embedding: BaseEmbedding, batch_size=10)；禁止 DenseEncoder(**config)。\n"
        "2. MODULAR encode(chunks: List[Chunk]) -> List[List[float]]；产品侧需 encode(text: str) -> List[float]，"
        "在 _get_encoder 内用 adapter 包装。\n"
        "3. import 保持 src.*（from src.ingestion.embedding.dense_encoder import DenseEncoder；"
        "from src.core.types import Chunk）。\n"
        "4. 单测无 API key：EmbeddingFactory/Settings 失败则 fallback stub（如 384 维非零向量）。\n"
        "5. 主任务若调用 self._get_encoder()，必须输出完整 def _get_encoder(self)。\n\n"
        "参考结构：\n"
        "```python\n"
        "    def _get_encoder(self):\n"
        "        if self._encoder is not None:\n"
        "            return self._encoder\n"
        "        from src.core.types import Chunk\n"
        "        from src.ingestion.embedding.dense_encoder import DenseEncoder\n"
        "        class _TextEncoderAdapter:\n"
        "            def __init__(self, dense):\n"
        "                self._dense = dense\n"
        "            def encode(self, text: str):\n"
        "                t = (text or '').strip() or ' '\n"
        "                vecs = self._dense.encode([Chunk(id='0', text=t, metadata={})])\n"
        "                return vecs[0] if vecs else []\n"
        "        try:\n"
        "            from src.libs.embedding.embedding_factory import EmbeddingFactory\n"
        "            from src.core.settings import Settings\n"
        "            settings = Settings.load(...)\n"
        "            emb = EmbeddingFactory.create(settings)\n"
        "            self._encoder = _TextEncoderAdapter(DenseEncoder(embedding=emb))\n"
        "        except Exception:\n"
        "            class _StubEncoder:\n"
        "                def encode(self, text: str):\n"
        "                    return [0.1] * 384\n"
        "            self._encoder = _StubEncoder()\n"
        "        return self._encoder\n"
        "```\n"
    )


def _build_llm_hint(primary_symbol: str, related: list[str]) -> str:
    extra = ""
    if related:
        extra = f"本轮 issues 还涉及: {', '.join(related)} — 同一 ```python 块内输出完整 def。\n\n"
    return (
        "=== LLMFactory / _get_llm / Message（tech_doc §1–§6 LLM 跨章约定）===\n"
        f"{extra}"
        "要点：\n"
        "1. LLMFactory.create(settings) 需要 Settings 对象，禁止 LLMFactory.create(dict)。\n"
        "2. 禁止从外部传入 llm；在 __init__ 或 _get_llm 内延迟 create 并缓存 self._llm。\n"
        "3. from src.libs.llm.base_llm import Message；resp = self._llm.chat(messages)；text = resp.content。\n"
        "4. import 保持 src.libs.llm.*，禁止 agent_rag.libs.*。\n"
        "5. 单测无 API key：create 失败时用 stub 返回 ChatResponse(content='...', model='stub')。\n"
        "6. LLM 调用失败须有非 LLM 回退（截断/TextRank/拼接）。\n\n"
        "参考 _get_llm：\n"
        "```python\n"
        "    def _get_llm(self):\n"
        "        if self._llm is not None:\n"
        "            return self._llm\n"
        "        try:\n"
        "            from src.libs.llm.llm_factory import LLMFactory\n"
        "            from src.core.settings import Settings\n"
        "            settings = Settings.load(...)\n"
        "            self._llm = LLMFactory.create(settings)\n"
        "        except Exception:\n"
        "            from src.libs.llm.base_llm import ChatResponse\n"
        "            class _StubLLM:\n"
        "                def chat(self, messages, **kwargs):\n"
        "                    return ChatResponse(content='stub summary', model='stub')\n"
        "            self._llm = _StubLLM()\n"
        "        return self._llm\n"
        "```\n"
    )


def _build_evidence_hint(primary_symbol: str, related: list[str]) -> str:
    return (
        "=== §1.0 证据抽取 _evidence_body / _evidence_chunks_from_result ===\n"
        "要点：\n"
        "1. _evidence_body(c)：优先 text_snippet，否则 text；皆空返回 ''。\n"
        "2. _evidence_chunks_from_result(result)：citations 非空则逐项映射；否则用 result['text'] 单条。\n"
        "3. compute_memory_similarity / add_short_term / compress_memory 等应复用二者。\n"
        "4. pytest 栈指向 helper 时，与主 symbol 同一 ```python 块输出完整 def。\n"
    )


def _build_mcp_client_hint(primary_symbol: str, related: list[str]) -> str:
    return (
        "=== McpClient.call_tool 归一化（tech_doc §3.1）===\n"
        "要点：\n"
        "1. __init__ 只保存已 initialize 的 underlying_session，不实现 list_tools。\n"
        "2. async def call_tool(name, arguments) -> dict：await self._session.call_tool(...)。\n"
        "3. 返回 dict 至少含 content(list)、isError(bool)；可选 structuredContent。\n"
        "4. content 须保留 text 与 image 块；type==image 保留 data/mimeType。\n"
        "5. 业务重试在 Executor.call_tool，不在 McpClient。\n"
    )


def _build_executor_hint(primary_symbol: str, related: list[str]) -> str:
    return (
        "=== Executor（tech_doc §3.2）===\n"
        "要点：\n"
        "1. __init__(mcp_client, config)：self._llm = LLMFactory.create(settings) 在 __init__ 内创建。\n"
        "2. async call_tool：await self._mcp.call_tool + 指数退避重试。\n"
        "3. async fill_arguments：Message 要求只输出 JSON object；用尽重试则抛异常。\n"
        "4. async execute_task：schema → fill_arguments → call_tool；填参失败返回 isError=True。\n"
    )


def _build_agent_llm_init_hint(primary_symbol: str, related: list[str]) -> str:
    return (
        "=== Agent 类 __init__ 内 LLM（tech_doc §4–§6）===\n"
        "要点：\n"
        "1. PlannerAgent / Evaluator / Generator：禁止外部传入 llm。\n"
        "2. __init__(config) 内 LLMFactory.create(settings)；后续方法复用 self._llm。\n"
        "3. JSON 输出类方法：system_prompt 禁止 markdown 围栏；解析前 strip 围栏。\n"
    )


def _build_storage_hint(primary_symbol: str, related: list[str]) -> str:
    return (
        "=== ChromaDB / SQLite / Qdrant（tech_doc §1）===\n"
        "要点：\n"
        "1. __init__ 接收外部 collection/conn 实例；单测用 mock。\n"
        "2. promote_to_long_term：compress_memory → long_term_collection.add(...)。\n"
        "3. add_event：SQLite + Qdrant（session_id、timestamp、embedding）。\n"
        "4. query_relevant_events：Qdrant search + SQLite 取 event_text。\n"
    )


def _build_import_rules_hint(primary_symbol: str, related: list[str]) -> str:
    return (
        "=== 跨项目 import 约定（tech_doc §0）===\n"
        "- 引用 MODULAR 父仓必须用 src.*（LLMFactory、DenseEncoder 等）。\n"
        "- 禁止 agent_rag.libs.* / agent_rag.ingestion.*。\n"
        "- API 报错（如缺 embedding）应修构造/adapter，不要改 import 路径。\n"
    )


_INTEGRATION_HINT_SPECS: tuple[IntegrationHintSpec, ...] = (
    IntegrationHintSpec(
        hint_id="import_rules",
        symbols=frozenset(),
        issue_patterns=(
            re.compile(r"ModuleNotFoundError.*\bsrc\b", re.I),
            re.compile(r"agent_rag\.(libs|ingestion)", re.I),
            re.compile(r"No module named ['\"]src", re.I),
        ),
        target_file_markers=("agent_rag/",),
        build=_build_import_rules_hint,
    ),
    IntegrationHintSpec(
        hint_id="encoder",
        symbols=frozenset(
            {
                "compute_memory_similarity",
                "add_short_term",
                "compress_memory",
                "get_relevant",
                "add_event",
                "query_relevant_events",
                "get_relevant_context",
                "__init__",
            }
        ),
        issue_patterns=(
            re.compile(r"DenseEncoder|_get_encoder|missing.*embedding|embedding.*参数", re.I),
            re.compile(r"encode\(.*Chunk|List\[Chunk\]", re.I),
        ),
        target_file_markers=("memory_manager.py", "context_manager.py"),
        build=_build_encoder_hint,
    ),
    IntegrationHintSpec(
        hint_id="llm",
        symbols=frozenset(
            {
                "compress_memory",
                "compress_short_term",
                "add_event",
                "retrieve_context",
                "get_relevant_context",
                "__init__",
            }
        ),
        issue_patterns=(
            re.compile(r"LLMFactory|_get_llm|BaseLLM|Message\(", re.I),
            re.compile(r"missing.*settings|settings\.llm", re.I),
        ),
        target_file_markers=(
            "memory_manager.py",
            "context_manager.py",
            "executor.py",
            "planner.py",
            "evaluator.py",
            "generator.py",
        ),
        build=_build_llm_hint,
    ),
    IntegrationHintSpec(
        hint_id="evidence",
        symbols=frozenset(
            {
                "_evidence_body",
                "_evidence_chunks_from_result",
                "compute_memory_similarity",
                "add_short_term",
                "promote_to_long_term",
                "add_event",
            }
        ),
        issue_patterns=(
            re.compile(r"_evidence_body|_evidence_chunks_from_result|text_snippet", re.I),
        ),
        target_file_markers=("memory_manager.py",),
        build=_build_evidence_hint,
    ),
    IntegrationHintSpec(
        hint_id="mcp_client",
        symbols=frozenset({"__init__", "call_tool"}),
        issue_patterns=(
            re.compile(r"McpClient|call_tool|ClientSession|structuredContent|isError", re.I),
            re.compile(r"type.*image|mimeType", re.I),
        ),
        target_file_markers=("mcp/client.py", "mcp/mcp_client.py"),
        build=_build_mcp_client_hint,
    ),
    IntegrationHintSpec(
        hint_id="executor",
        symbols=frozenset({"__init__", "call_tool", "fill_arguments", "execute_task"}),
        issue_patterns=(
            re.compile(r"Executor|fill_arguments|execute_task|ArgumentFill|input_schema", re.I),
        ),
        target_file_markers=("mcp/executor.py",),
        build=_build_executor_hint,
    ),
    IntegrationHintSpec(
        hint_id="agent_llm",
        symbols=frozenset(
            {
                "__init__",
                "plan",
                "replan",
                "evaluate",
                "quick_rule_check",
                "draft_partial_answer",
                "choose_next_action",
                "run_subtask",
            }
        ),
        issue_patterns=(re.compile(r"PlannerAgent|Evaluator|Generator|self\._llm", re.I),),
        target_file_markers=(
            "agents/planner.py",
            "agents/evaluator.py",
            "agents/generator.py",
        ),
        build=_build_agent_llm_init_hint,
    ),
    IntegrationHintSpec(
        hint_id="storage",
        symbols=frozenset({"promote_to_long_term", "add_event", "query_relevant_events", "__init__"}),
        issue_patterns=(re.compile(r"Chroma|Qdrant|sqlite|long_term_collection", re.I),),
        target_file_markers=("memory_manager.py",),
        build=_build_storage_hint,
    ),
)


def matched_hint_specs(
    *,
    symbol: str,
    issues: str = "",
    target_file: str = "",
) -> list[IntegrationHintSpec]:
    seen: set[str] = set()
    out: list[IntegrationHintSpec] = []
    for spec in _INTEGRATION_HINT_SPECS:
        if spec.hint_id in seen:
            continue
        if _matches(spec, symbol=symbol, issues=issues, target_file=target_file):
            seen.add(spec.hint_id)
            out.append(spec)
    return out


def needs_integration_hints(
    *,
    symbol: str,
    issues: str = "",
    target_file: str = "",
) -> bool:
    return bool(matched_hint_specs(symbol=symbol, issues=issues, target_file=target_file))


def collect_integration_hints(
    *,
    symbol: str,
    issues: str = "",
    target_file: str = "",
    primary_symbol: str | None = None,
) -> str:
    primary = primary_symbol or symbol
    specs = matched_hint_specs(symbol=symbol, issues=issues, target_file=target_file)
    if not specs:
        return ""
    related = related_symbols_from_issues(issues, primary)
    blocks = [spec.build(primary, related) for spec in specs]
    return "\n".join(blocks) + "\n"


ENCODER_RELATED_SYMBOLS = next(
    s.symbols for s in _INTEGRATION_HINT_SPECS if s.hint_id == "encoder"
)


def needs_encoder_hint(*, symbol: str, issues: str = "") -> bool:
    return needs_integration_hints(symbol=symbol, issues=issues)


def encoder_implementation_hint(*, primary_symbol: str, related: list[str] | None = None) -> str:
    return _build_encoder_hint(primary_symbol, related or [])


def integration_hints_enabled(harness_cfg: dict | None) -> bool:
    """读取 harness.yaml 中 generator.inject_integration_hints（兼容 inject_encoder_hint）。"""
    gen_cfg = (harness_cfg or {}).get("generator") or {}
    if "inject_integration_hints" in gen_cfg:
        return bool(gen_cfg.get("inject_integration_hints"))
    return bool(gen_cfg.get("inject_encoder_hint", True))
