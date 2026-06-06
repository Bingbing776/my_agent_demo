"""
§7 RagOrchestrator — Plan-and-Solve 主循环、全局门禁、终稿合成。

规格：docs/tech_doc.md §7。
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_DEFAULT_GLOBAL_READINESS_PROMPT = """你是全局答案就绪评审。只输出一个合法 JSON 对象，无 markdown 围栏。
键仅：sufficient_for_answer (bool)、need_replan (bool)、issues (list[str])、
observation_for_replan (str)、suggested_retrieval_changes (list，元素为 dict 或 str)。
need_replan=True 时 observation_for_replan 须非空。"""

_DEFAULT_FINAL_SYNTHESIS_PROMPT = """你是 RAG 终稿撰写器。根据证据包撰写完整、准确的答案。

【强制要求】
1. 答案末尾必须附上「引用来源」段，列出每条被引用的证据来源（文件名、章节等）。
2. 答案正文中用 [1]、[2] 等编号标注引用位置，与末尾来源列表对应。
3. 禁止编造证据包未出现的事实；不确定处写「依据现有检索未找到…」。
4. 可使用 Markdown 格式。

【输出格式示例】
TOPMOST 主要解决... [1]。它通过... [2]。

---
**引用来源**
- [1] 文件名.pdf (章节: Abstract)
- [2] 文件名.pdf (章节: Introduction)
"""

_RETRIEVAL_TOOL_NAMES = frozenset({
    "query_knowledge_hub",
    "search_by_metadata",
    "get_neighbor_chunks",
    "get_document_full_text",
    "read_chunk",
    "list_documents",
})

_EVIDENCE_CHUNK_ID_RE = re.compile(r"\b([a-f0-9]{8}_[0-9]{4}_[a-f0-9]{8})\b", re.IGNORECASE)
_EVIDENCE_DOC_ID_RE = re.compile(r"\b(doc_[a-f0-9]+)\b", re.IGNORECASE)


class RagOrchestrator:
    """RAG Agent 主控制器：Plan-and-Solve + 全局门禁 + 终稿合成。"""

    def __init__(
        self,
        config: dict = None,
        *,
        long_term_collection=None,
        sqlite_conn=None,
        qdrant_collection=None,
    ):
        # 如果没有传入 config，从 settings.yaml 自动加载
        if not config:
            try:
                from src.core.settings import load_settings
                from pathlib import Path as _Path
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
                # MCP server 在 mcp_rag 目录
                # 从当前文件位置推算绝对路径
                _agent_rag_root = _Path(__file__).resolve().parents[2]
                _mcp_cwd = str(_agent_rag_root.parent / "mcp_rag")
                config = {
                    "llm": {
                        "provider": settings.llm.provider,
                        "model": settings.llm.model,
                        "api_key": settings.llm.api_key,
                    },
                    "rag_agent": {
                        "mcp": {
                            "stdio": {
                                "command": "python",
                                "args": ["-m", "src.mcp_server.server"],
                                "cwd": _mcp_cwd,
                            }
                        }
                    }
                }
            except Exception:
                config = {}

        self._config = dict(config or {})
        rag_cfg = self._config.get("rag_agent", {}) or {}
        if not isinstance(rag_cfg, dict):
            rag_cfg = {}

        memory_cfg = dict(rag_cfg.get("memory", rag_cfg))
        if "llm" not in memory_cfg and "llm" in self._config:
            memory_cfg["llm"] = self._config["llm"]

        from agent_rag.memory.memory_manager import MemoryManager
        from agent_rag.context.context_manager import ContextManager
        from agent_rag.agents.planner import PlannerAgent
        from agent_rag.agents.evaluator import Evaluator
        from agent_rag.agents.generator import Generator

        ltc, sql, qdr = long_term_collection, sqlite_conn, qdrant_collection

        # 按 tech_doc §7 步骤 2：如果外部未传入数据库连接，根据 config 自动构建
        if ltc is None and sql is None and qdr is None:
            # ChromaDB 长期记忆
            try:
                import chromadb
                vs_cfg = self._config.get("vector_store", {}) or {}
                persist_dir = vs_cfg.get("persist_directory", "./data/db/chroma")
                collection_name = memory_cfg.get("collection_name", "long_term_memory")
                chroma_client = chromadb.PersistentClient(path=str(Path(persist_dir)))
                ltc = chroma_client.get_or_create_collection(name=collection_name)
            except Exception as _e:
                import logging
                logging.debug(f"ChromaDB init skipped: {_e}")

            # SQLite 情景记忆（结构化存储）
            try:
                import sqlite3
                sqlite_path = memory_cfg.get("sqlite_path", "./data/db/episodic_memory.db")
                Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
                sql = sqlite3.connect(str(sqlite_path), check_same_thread=False)
                # 创建情景记忆表（如果不存在）
                sql.execute("""
                    CREATE TABLE IF NOT EXISTS episodic_events (
                        event_id TEXT PRIMARY KEY,
                        event_text TEXT,
                        session_id TEXT,
                        timestamp TEXT,
                        related_chunks TEXT
                    )
                """)
                sql.commit()
            except Exception as _e:
                import logging
                logging.debug(f"SQLite init skipped: {_e}")

            # Qdrant 情景记忆（向量存储）
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams
                qdrant_cfg = memory_cfg.get("qdrant", {}) or {}
                qdrant_path = qdrant_cfg.get("path", "./data/db/qdrant")
                Path(qdrant_path).mkdir(parents=True, exist_ok=True)
                qdr_client = QdrantClient(path=str(qdrant_path))
                qdrant_collection_name = qdrant_cfg.get("collection_name", "episodic_memory")
                # 创建 collection（如果不存在）
                collections = [c.name for c in qdr_client.get_collections().collections]
                if qdrant_collection_name not in collections:
                    qdr_client.create_collection(
                        collection_name=qdrant_collection_name,
                        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                    )
                qdr = qdr_client
            except Exception as _e:
                import logging
                logging.debug(f"Qdrant init skipped: {_e}")

        self._memory = MemoryManager(
            long_term_collection=ltc,
            sqlite_conn=sql,
            qdrant_collection=qdr,
            config=memory_cfg,
        )

        context_cfg = dict(rag_cfg.get("context", rag_cfg))
        if "llm" not in context_cfg and "llm" in self._config:
            context_cfg["llm"] = self._config["llm"]
        self._context = ContextManager(config=context_cfg)

        planner_cfg = dict(rag_cfg)
        if "llm" not in planner_cfg and "llm" in self._config:
            planner_cfg["llm"] = self._config["llm"]
        self._planner = PlannerAgent(config=planner_cfg)

        agent_cfg = dict(rag_cfg)
        if "llm" not in agent_cfg and "llm" in self._config:
            agent_cfg["llm"] = self._config["llm"]
        self._evaluator = Evaluator(config=agent_cfg)
        self._generator = Generator(config=agent_cfg)

        self._tools_by_name: dict[str, Any] = {}
        self._mcp_session: Any = None
        self._executor: Any = None
        self._mcp_stack: Any = None
        self._mcp_loop_id: int | None = None
        self._llm: Any = None

    def _mcp_cfg(self) -> dict:
        rag = self._config.get("rag_agent", {}) or {}
        mcp = rag.get("mcp", {}) if isinstance(rag, dict) else {}
        return mcp if isinstance(mcp, dict) else {}

    def _mcp_persistent_stdio(self) -> bool:
        return bool(self._mcp_cfg().get("persistent_stdio", False))

    def _resolve_mcp_stdio_cfg(self, mcp_stdio: dict) -> dict:
        stdio_cfg = dict(mcp_stdio)
        cwd = stdio_cfg.get("cwd")
        if cwd and not Path(str(cwd)).is_absolute():
            agent_root = Path(__file__).resolve().parents[2]
            repo_root = agent_root.parent
            for candidate in (
                (agent_root / cwd).resolve(),
                (repo_root / "mcp_rag").resolve(),
            ):
                if candidate.is_dir() and (candidate / "src" / "mcp_server" / "server.py").exists():
                    stdio_cfg["cwd"] = str(candidate)
                    break
            else:
                stdio_cfg["cwd"] = str((agent_root / cwd).resolve())
        return stdio_cfg

    async def close_mcp(self) -> None:
        """关闭持久 MCP stdio 会话（Dashboard 退出时可调用）。"""
        if self._mcp_stack is not None:
            try:
                await self._mcp_stack.aclose()
            except Exception as exc:
                logger.debug("close_mcp: %s", exc)
        self._mcp_stack = None
        self._mcp_session = None
        self._executor = None
        self._tools_by_name = {}
        self._mcp_loop_id = None

    async def _ensure_mcp_connected(self, mcp_stdio: dict) -> bool:
        """持久模式：复用同一 MCP 子进程，供 Dashboard 多轮提问。"""
        import asyncio as _asyncio

        try:
            loop_id = id(_asyncio.get_running_loop())
        except RuntimeError:
            loop_id = None

        if (
            self._executor is not None
            and self._mcp_session is not None
            and self._mcp_loop_id == loop_id
        ):
            return True

        if self._executor is not None and self._mcp_loop_id != loop_id:
            logger.info("MCP session bound to a different event loop; reconnecting")
            await self.close_mcp()

        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from agent_rag.mcp.mcp_client import McpClient
        from agent_rag.mcp.executor import Executor

        stdio_cfg = self._resolve_mcp_stdio_cfg(mcp_stdio)
        params = StdioServerParameters(
            command=stdio_cfg.get("command", "python"),
            args=list(stdio_cfg.get("args") or []),
            env={**os.environ, **(stdio_cfg.get("env") or {})},
            cwd=stdio_cfg.get("cwd"),
        )
        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._mcp_stack = stack
        self._mcp_session = session
        rag_cfg = self._config.get("rag_agent", {}) or {}
        self._executor = Executor(
            mcp_client=McpClient(session=session, config=rag_cfg),
            config=rag_cfg,
        )
        self._mcp_loop_id = loop_id
        return True

    def _orchestrator_cfg(self) -> dict:
        rag = self._config.get("rag_agent", {}) or {}
        orch = rag.get("orchestrator", {}) if isinstance(rag, dict) else {}
        return orch if isinstance(orch, dict) else {}

    def _get_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        if getattr(self._planner, "_llm", None) is not None:
            self._llm = self._planner._llm
            return self._llm
        try:
            from src.core.settings import load_settings
            from src.libs.llm.llm_factory import LLMFactory

            from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            self._llm = LLMFactory.create(settings)
        except Exception as e:
            import logging
            logging.warning(f"Failed to load real LLM: {e}, using stub")
            from src.libs.llm.base_llm import ChatResponse

            class _StubLLM:
                def chat(self, messages, **kwargs):
                    return ChatResponse(
                        content=json.dumps(
                            {
                                "sufficient_for_answer": True,
                                "need_replan": False,
                                "issues": [],
                                "observation_for_replan": "",
                                "suggested_retrieval_changes": [],
                            }
                        ),
                        model="stub",
                    )

            self._llm = _StubLLM()
        return self._llm

    async def _ensure_tools_cache(self) -> None:
        if self._tools_by_name and self._mcp_session is not None:
            return
        if self._mcp_session is None:
            raise RuntimeError("MCP session not open; call from answer() async with block")
        result = await self._mcp_session.list_tools()
        tools = getattr(result, "tools", None) or result
        self._tools_by_name = {}
        for tool in tools or []:
            name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
            if not name:
                continue
            if isinstance(tool, dict):
                self._tools_by_name[name] = tool
            else:
                desc = getattr(tool, "description", "") or ""
                schema = getattr(tool, "inputSchema", None) or {}
                self._tools_by_name[name] = {
                    "name": name,
                    "description": desc,
                    "inputSchema": schema,
                }

    def build_tool_index_text(self) -> str:
        line_cap = int(self._orchestrator_cfg().get("tool_index_line_max_chars", 200))
        lines: list[str] = []
        for name in sorted(self._tools_by_name.keys()):
            tool = self._tools_by_name[name]
            if isinstance(tool, dict):
                desc = str(tool.get("description", ""))
                schema = tool.get("inputSchema")
                if not desc and schema is None and "name" in tool:
                    desc = ""
            else:
                desc = str(getattr(tool, "description", "") or "")
            desc = desc.replace("\n", " ").strip()
            if line_cap and len(desc) > line_cap:
                desc = desc[: line_cap - 3] + "..."
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def get_input_schema(self, tool_name: str) -> dict:
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            raise KeyError(f"unknown tool: {tool_name}")
        if isinstance(tool, dict):
            schema = tool.get("inputSchema")
            return dict(schema) if isinstance(schema, dict) else {}
        schema = getattr(tool, "inputSchema", None)
        return dict(schema) if isinstance(schema, dict) else {}

    def _build_final_evidence_bundle(self, query: str, subtask_results: list) -> str:
        orch = self._orchestrator_cfg()
        draft_cap = int(orch.get("final_evidence_draft_max_chars", 800))
        trace_cap = int(orch.get("final_evidence_trace_max_chars", 400))
        bundle_cap = int(orch.get("final_evidence_bundle_max_chars", 12000))

        items = list(subtask_results or [])
        with_id = [r for r in items if isinstance(r, dict) and r.get("task_id")]
        if with_id:
            items = sorted(items, key=lambda r: str(r.get("task_id", "")))

        parts: list[str] = [f"# 用户问题\n{query}\n"]
        for result in items:
            if not isinstance(result, dict):
                continue
            task_id = result.get("task_id", "?")
            status = result.get("status", "?")
            draft = str(result.get("draft_text") or "")
            if draft_cap and len(draft) > draft_cap:
                draft = draft[: draft_cap - 13] + "…[truncated]"
            trace_lines: list[str] = []
            for step in result.get("tool_trace") or []:
                if not isinstance(step, dict):
                    continue
                summary = str(step.get("summary", ""))
                if trace_cap and len(summary) > trace_cap:
                    summary = summary[: trace_cap - 13] + "…[truncated]"
                trace_lines.append(f"  {step.get('tool_name', '?')}: {summary}")
            block = f"## {task_id} ({status})\n{draft}\n" + "\n".join(trace_lines)
            parts.append(block)

        bundle = "\n---\n".join(parts)
        if bundle_cap and len(bundle) > bundle_cap:
            bundle = bundle[: bundle_cap - 13] + "…[truncated]"
            logger.warning("evidence bundle truncated to %s chars", bundle_cap)
        return bundle

    @staticmethod
    def _extract_evidence_ids(text: str) -> set[str]:
        if not text:
            return set()
        ids = set(_EVIDENCE_CHUNK_ID_RE.findall(str(text)))
        ids.update(_EVIDENCE_DOC_ID_RE.findall(str(text)))
        return ids

    @classmethod
    def _extract_ids_from_subtask_result(cls, result: dict) -> set[str]:
        ids: set[str] = set()
        if not isinstance(result, dict):
            return ids
        for trace in result.get("tool_trace") or []:
            if isinstance(trace, dict):
                ids |= cls._extract_evidence_ids(str(trace.get("summary", "")))
        ids |= cls._extract_evidence_ids(str(result.get("draft_text", "")))
        return ids

    @staticmethod
    def _subtask_did_retrieval(result: dict) -> bool:
        if not isinstance(result, dict):
            return False
        for trace in result.get("tool_trace") or []:
            if isinstance(trace, dict) and trace.get("tool_name") in _RETRIEVAL_TOOL_NAMES:
                return True
        return False

    def _parse_json_object(self, content: str) -> dict | None:
        text = (content or "").strip()
        fence = re.match(r"^```(?:json)?\s*\n([\s\S]*?)\n```\s*$", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def _check_global_answer_readiness(
        self,
        query: str,
        evidence_bundle: str,
        context: str = "",
    ) -> dict:
        from src.libs.llm.base_llm import Message

        system = self._orchestrator_cfg().get(
            "global_readiness_system_prompt", _DEFAULT_GLOBAL_READINESS_PROMPT
        )
        user = (
            f"用户问题\n{query or '（无）'}\n\n"
            f"对话/记忆摘要\n{context or '（无）'}\n\n"
            f"证据包\n{evidence_bundle or '（无）'}"
        )
        try:
            response = self._get_llm().chat(
                [Message(role="system", content=system), Message(role="user", content=user)]
            )
            parsed = self._parse_json_object(getattr(response, "content", "") or "")
            if parsed:
                issues = parsed.get("issues", [])
                if isinstance(issues, str):
                    issues = [issues] if issues.strip() else []
                elif not isinstance(issues, list):
                    issues = []
                changes = parsed.get("suggested_retrieval_changes", [])
                if not isinstance(changes, list):
                    changes = []
                return {
                    "sufficient_for_answer": bool(parsed.get("sufficient_for_answer", False)),
                    "need_replan": bool(parsed.get("need_replan", False)),
                    "issues": issues,
                    "observation_for_replan": str(parsed.get("observation_for_replan") or ""),
                    "suggested_retrieval_changes": changes,
                }
        except Exception as exc:
            logger.warning("_check_global_answer_readiness LLM failed: %s", exc)
        return {
            "sufficient_for_answer": False,
            "need_replan": True,
            "issues": ["global readiness LLM parse failed"],
            "observation_for_replan": "retry retrieval with broader query",
            "suggested_retrieval_changes": [],
        }

    async def _synthesize_final_answer(
        self,
        query: str,
        evidence_bundle: str,
        context: str = "",
    ) -> str:
        from src.libs.llm.base_llm import Message

        system = self._orchestrator_cfg().get(
            "final_synthesis_system_prompt", _DEFAULT_FINAL_SYNTHESIS_PROMPT
        )
        user = (
            f"用户问题\n{query or ''}\n\n"
            f"对话/记忆摘要\n{context or '（无）'}\n\n"
            f"证据包\n{evidence_bundle or '（无）'}"
        )
        try:
            response = self._get_llm().chat(
                [Message(role="system", content=system), Message(role="user", content=user)]
            )
            text = (getattr(response, "content", "") or "").strip()
            if text:
                return text
        except Exception as exc:
            logger.warning("_synthesize_final_answer LLM failed: %s", exc)
        return evidence_bundle[:2000] if evidence_bundle else "[synthesis_failed]"

    def _merge_subtask_images(self, subtask_results: list) -> list:
        orch = self._orchestrator_cfg()
        max_images = int(orch.get("answer_max_images", 0) or 0)
        seen: set[str] = set()
        merged: list[dict] = []

        def _add(img: dict) -> None:
            if not isinstance(img, dict) or not img.get("data"):
                return
            key = str(img["data"])[:64]
            if key in seen:
                return
            seen.add(key)
            merged.append(dict(img))
            if max_images > 0 and len(merged) >= max_images:
                return

        for item in subtask_results or []:
            if isinstance(item, dict) and "data" in item:
                _add(item)
                continue
            if isinstance(item, (list, tuple)):
                for sub in item:
                    if isinstance(sub, dict) and sub.get("data"):
                        _add(sub)
                    elif isinstance(sub, (list, tuple)):
                        for img in sub:
                            if isinstance(img, dict):
                                _add(img)
                continue
            if isinstance(item, dict):
                for img in item.get("images") or []:
                    if isinstance(img, dict):
                        _add(img)
        return merged

    def _should_attach_images(self, merged_images: list, query: str) -> bool:
        if not merged_images:
            return False
        orch = self._orchestrator_cfg()
        if not orch.get("attach_images_when_present", True):
            return False
        keywords = orch.get(
            "image_query_keywords",
            ["图", "表", "截图", "figure", "image", "chart", "diagram"],
        )
        q = (query or "").lower()
        for kw in keywords:
            if kw.lower() in q:
                return True
        return bool(merged_images)

    async def answer(self, query: str, session_id: str | None = None) -> dict:
        orch = self._orchestrator_cfg()
        max_global_replan = int(orch.get("max_global_replan_rounds", 2))
        max_subtask_replan = int(orch.get("max_subtask_replan_rounds", 5))
        max_subtasks_total = int(orch.get("max_subtasks_total", 20))
        skip_stale_retrieval = bool(orch.get("skip_replan_when_no_new_evidence", True))
        stale_retrieval_threshold = int(orch.get("no_new_evidence_replan_streak", 1))
        allow_insufficient = bool(orch.get("allow_final_on_insufficient_evidence", False))

        mcp_stdio = self._config.get("mcp", {}).get("stdio") or self._config.get(
            "rag_agent", {}
        ).get("mcp", {}).get("stdio")
        persistent_mcp = self._mcp_persistent_stdio()

        # 非持久模式：每次 answer 新建 MCP（run_test / 单次脚本）
        if not persistent_mcp:
            await self.close_mcp()

        async def _run_pipeline() -> dict:
            context_text = ""
            try:
                mem_ctx = self._memory.retrieve_context(query, session_id=session_id)
                if isinstance(mem_ctx, str):
                    context_text = mem_ctx
            except Exception as exc:
                logger.debug("retrieve_context skipped: %s", exc)
            try:
                ctx = self._context.get_relevant_context(query)
                if ctx:
                    context_text = f"{context_text}\n{ctx}".strip() if context_text else str(ctx)
            except Exception as exc:
                logger.debug("get_relevant_context skipped: %s", exc)

            await self._ensure_tools_cache()
            tool_index = self.build_tool_index_text()
            routing_hint = ""
            try:
                routing_hint = self._planner.load_routing_hint()
            except Exception:
                pass

            subtask_results: list[dict] = []
            global_replan_round = 0
            subtask_replan_round = 0
            subtasks_executed = 0
            seen_evidence_ids: set[str] = set()
            stale_retrieval_streak = 0
            retrieval_stalled = False

            task_queue: deque = deque()
            try:
                plan_result = self._planner.plan(
                    query, context_text, tool_index, routing_hint
                )
                for t in plan_result or []:
                    task_queue.append(t)
            except Exception as exc:
                logger.warning("plan failed: %s", exc)
                task_queue.append(
                    {
                        "id": "fallback-1",
                        "description": query,
                        "intent": "retrieve",
                        "suggested_tool": "query_knowledge_hub",
                    }
                )

            tool_names = list(self._tools_by_name.keys())
            # 累积前面子任务的工具调用结果，传给后续子任务
            accumulated_evidence = ""

            while True:
                while task_queue:
                    if subtasks_executed >= max_subtasks_total:
                        logger.warning(
                            "max_subtasks_total (%s) reached; stopping subtask queue",
                            max_subtasks_total,
                        )
                        print(
                            f"[DEBUG Orch] max_subtasks_total ({max_subtasks_total}) reached, "
                            "proceeding to final synthesis",
                            flush=True,
                        )
                        break
                    task = task_queue.popleft()
                    # 把前面子任务的结果作为上下文传给当前子任务
                    if accumulated_evidence:
                        task["prior_observation"] = accumulated_evidence
                    print(f"[DEBUG Orch] Running subtask {task.get('id')}, prior_obs length={len(task.get('prior_observation', ''))}", flush=True)
                    result = await self._generator.run_subtask(
                        query,
                        task,
                        self._executor,
                        self.get_input_schema,
                        self._evaluator,
                        tool_names=tool_names,
                    )
                    subtasks_executed += 1
                    subtask_results.append(result)
                    # 累积当前子任务的工具调用摘要
                    if isinstance(result, dict) and result.get("tool_trace"):
                        for trace in result["tool_trace"]:
                            summary = str(trace.get("summary", ""))
                            if summary:
                                accumulated_evidence += f"\n{trace.get('tool_name', '')}: {summary}"

                    if skip_stale_retrieval and self._subtask_did_retrieval(result):
                        result_ids = self._extract_ids_from_subtask_result(result)
                        new_ids = result_ids - seen_evidence_ids
                        seen_evidence_ids |= result_ids
                        if not new_ids:
                            stale_retrieval_streak += 1
                            print(
                                f"[DEBUG Orch] retrieval added no new chunk/doc ids "
                                f"(streak={stale_retrieval_streak})",
                                flush=True,
                            )
                        else:
                            stale_retrieval_streak = 0
                    elif skip_stale_retrieval:
                        seen_evidence_ids |= self._extract_ids_from_subtask_result(result)

                    if (
                        skip_stale_retrieval
                        and not retrieval_stalled
                        and stale_retrieval_streak >= stale_retrieval_threshold
                    ):
                        retrieval_stalled = True
                        logger.warning(
                            "Retrieval repeated with no new evidence (%s consecutive); "
                            "stopping search",
                            stale_retrieval_streak,
                        )
                        print(
                            "[DEBUG Orch] repeated retrieval results, stopping search and "
                            "proceeding to final synthesis",
                            flush=True,
                        )
                        task_queue.clear()
                        break

                    if result.get("status") == "needs_replan":
                        if retrieval_stalled:
                            task_queue.clear()
                            break
                        obs = result.get("observation_for_replan") or ""
                        if subtask_replan_round < max_subtask_replan:
                            try:
                                new_tasks = self._planner.replan(
                                    query, context_text, tool_index, routing_hint, obs
                                )
                                for t in new_tasks or []:
                                    task_queue.append(t)
                            except Exception as exc:
                                logger.warning("replan failed: %s", exc)
                            subtask_replan_round += 1
                        else:
                            logger.warning(
                                "max_subtask_replan_rounds (%s) reached; skipping subtask replan",
                                max_subtask_replan,
                            )
                            print(
                                f"[DEBUG Orch] max_subtask_replan_rounds ({max_subtask_replan}) "
                                "reached, proceeding with existing results",
                                flush=True,
                            )

                evidence_bundle = self._build_final_evidence_bundle(query, subtask_results)
                readiness = await self._check_global_answer_readiness(
                    query, evidence_bundle, context_text
                )

                if readiness.get("need_replan") and global_replan_round < max_global_replan and not retrieval_stalled:
                    obs_parts = [readiness.get("observation_for_replan") or ""]
                    issues = readiness.get("issues") or []
                    if issues:
                        obs_parts.append("; ".join(str(i) for i in issues))
                    changes = readiness.get("suggested_retrieval_changes") or []
                    if changes:
                        obs_parts.append(str(changes))
                    try:
                        new_tasks = self._planner.replan(
                            query,
                            context_text,
                            tool_index,
                            routing_hint,
                            "\n".join(p for p in obs_parts if p),
                        )
                        for t in new_tasks or []:
                            task_queue.append(t)
                    except Exception as exc:
                        logger.warning("global replan failed: %s", exc)
                    global_replan_round += 1
                    if task_queue:
                        continue

                sufficient = readiness.get("sufficient_for_answer")
                if sufficient or allow_insufficient:
                    final_text = await self._synthesize_final_answer(
                        query, evidence_bundle, context_text
                    )
                else:
                    drafts = [
                        str(r.get("draft_text") or "")
                        for r in subtask_results
                        if isinstance(r, dict)
                    ]
                    final_text = "\n\n".join(d for d in drafts if d) or "证据不足，无法生成完整答案。"

                merged_images = self._merge_subtask_images(subtask_results)
                answer_images = merged_images if self._should_attach_images(merged_images, query) else []

                # 提取 chunks 用于记忆
                chunks_for_memory = []
                for r in subtask_results:
                    if isinstance(r, dict):
                        draft = r.get("draft_text", "")
                        task_id = r.get("task_id", "")
                        for step in r.get("tool_trace", []):
                            if isinstance(step, dict):
                                summary = step.get("summary", "")
                                if summary:
                                    chunks_for_memory.append({
                                        "source": f"task_{task_id}",
                                        "chunk_id": f"{task_id}_{step.get('tool_name', '')}",
                                        "text_snippet": summary[:500],
                                    })

                try:
                    self._memory.add_short_term(
                        query,
                        {"query": query, "text": final_text, "citations": [], "chunks": chunks_for_memory},
                        session_id=session_id or "default",
                    )
                except Exception as exc:
                    logger.debug("add_short_term skipped: %s", exc)
                try:
                    self._context.update_context(query, final_text)
                except Exception as exc:
                    logger.debug("update_context skipped: %s", exc)

                # 尝试将符合条件的短期记忆升级到长期记忆（内部会调用 add_event）
                try:
                    self._memory.promote_to_long_term()
                except Exception as exc:
                    logger.warning("promote_to_long_term failed: %s", exc)
                    import traceback
                    traceback.print_exc()
                    logger.warning("add_event failed: %s", exc)
                    import traceback
                    traceback.print_exc()

                return {"text": final_text, "images": answer_images}

        if mcp_stdio:
            if persistent_mcp:
                try:
                    await self._ensure_mcp_connected(mcp_stdio)
                    return await _run_pipeline()
                except ImportError as imp_err:
                    logger.warning("mcp SDK not available; running without MCP")
                    print(f"[DEBUG] MCP ImportError: {imp_err}", flush=True)
                except Exception as exc:
                    logger.warning("MCP connect failed: %s", exc)
                    print(f"[DEBUG] MCP connect failed: {exc}", flush=True)
                    await self.close_mcp()
            else:
                try:
                    from mcp import ClientSession, StdioServerParameters
                    from mcp.client.stdio import stdio_client
                    from agent_rag.mcp.mcp_client import McpClient
                    from agent_rag.mcp.executor import Executor

                    stdio_cfg = self._resolve_mcp_stdio_cfg(mcp_stdio)
                    params = StdioServerParameters(
                        command=stdio_cfg.get("command", "python"),
                        args=list(stdio_cfg.get("args") or []),
                        env={**os.environ, **(stdio_cfg.get("env") or {})},
                        cwd=stdio_cfg.get("cwd"),
                    )
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            self._mcp_session = session
                            rag_cfg = self._config.get("rag_agent", {}) or {}
                            self._executor = Executor(
                                mcp_client=McpClient(session=session, config=rag_cfg),
                                config=rag_cfg,
                            )
                            return await _run_pipeline()
                except ImportError as imp_err:
                    logger.warning("mcp SDK not available; running without MCP")
                    print(f"[DEBUG] MCP ImportError: {imp_err}", flush=True)
                except Exception as exc:
                    logger.warning("MCP connect failed: %s", exc)
                    print(f"[DEBUG] MCP connect failed: {exc}", flush=True)
                    import traceback
                    traceback.print_exc()

        if self._executor is None:
            from unittest.mock import AsyncMock, MagicMock

            mock_session = MagicMock()
            mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
            self._mcp_session = mock_session
            from agent_rag.mcp.mcp_client import McpClient
            from agent_rag.mcp.executor import Executor

            rag_cfg = self._config.get("rag_agent", {}) or {}
            mock_client = McpClient(session=mock_session, config=rag_cfg)
            self._executor = Executor(mcp_client=mock_client, config=rag_cfg)

        return await _run_pipeline()
