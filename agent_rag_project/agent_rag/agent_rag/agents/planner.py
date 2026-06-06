class PlannerAgent:
    """§4 PlannerAgent — 对用户问题做子任务规划（tool 名级）。

    规格：docs/tech_doc.md §4。
    """

    def __init__(self, config: dict = None, routing_skill_path: str = None):
        self._config = config or {}

        # 在 __init__ 内创建 LLM 实例（禁止从外部传入）
        self._llm = None

        # 路由启发文件路径
        self._routing_skill_path = routing_skill_path if routing_skill_path is not None else self._config.get("routing_skill_path")
        self._routing_hint_cache = None

        # 不在此类内连接 MCP、不持有 tools_by_name

    def _get_llm(self):
        """延迟创建并缓存 LLM 实例，使用配置的 llm 段或全局 Settings。

        返回的实例兼容 BaseLLM 的 chat 接口。
        """
        if self._llm is not None:
            return self._llm

        try:
            from src.libs.llm.llm_factory import LLMFactory
            from src.core.settings import load_settings

            llm_config = self._config.get("llm", {})
            if llm_config:
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            else:
                from pathlib import Path as _P; settings = load_settings(_P(__file__).resolve().parents[2] / "config" / "settings.yaml")
            self._llm = LLMFactory.create(settings)
        except Exception as e:
            print(f"[DEBUG Planner._get_llm] FAILED: {type(e).__name__}: {e}", flush=True)
            from src.libs.llm.base_llm import ChatResponse

            class _StubLLM:
                def chat(self, messages, **kwargs):
                    return ChatResponse(content='stub response', model='stub')

            self._llm = _StubLLM()

        return self._llm

    def load_routing_hint(self) -> str:
        """生成供 plan/replan 使用的 routing_hint（从 mcp-tool-router.md 抽取 MUST + 主路由表）。"""
        import logging
        import re

        logger = logging.getLogger(__name__)

        if self._routing_hint_cache is not None:
            return self._routing_hint_cache

        if not self._routing_skill_path:
            return ""

        try:
            with open(self._routing_skill_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        except Exception:
            logger.warning("无法读取 routing skill 文件: %s", self._routing_skill_path)
            return ""

        lines = raw.splitlines(keepends=True)
        content_start = 0
        if lines and lines[0].strip() == '---':
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
            if end is not None:
                content_start = end + 1
        content = ''.join(lines[content_start:])

        must_header = re.compile(r'^#{1,6}\s+.*(MUST|硬规则).*', re.IGNORECASE | re.MULTILINE)
        routing_header = re.compile(r'^#{1,6}\s+.*主路由表.*', re.MULTILINE)

        def _extract_section(match):
            header_line = match.group(0)
            level = len(header_line) - len(header_line.lstrip('#'))
            start = match.start()
            remaining = content[start + len(header_line):]
            next_section_re = re.compile(r'^#{1,' + str(level) + r'}\s+.+$', re.MULTILINE)
            next_match = next_section_re.search(remaining)
            section_end = start + len(header_line) + (next_match.start() if next_match else len(remaining))
            return content[start:section_end].strip()

        must_match = must_header.search(content)
        routing_match = routing_header.search(content)

        parts = []
        if must_match:
            must_section = _extract_section(must_match)
            if must_section:
                parts.append(must_section)
        if routing_match:
            routing_section = _extract_section(routing_match)
            if routing_section:
                parts.append(routing_section)

        if parts:
            if len(parts) == 2:
                if parts[0] in parts[1]:
                    hint = parts[1]
                elif parts[1] in parts[0]:
                    hint = parts[0]
                else:
                    hint = "\n\n".join(parts)
            else:
                hint = parts[0]
        else:
            hint = content.strip()
            logger.info("未能从 routing skill 文件提取到有效段落，使用全文作为 routing hint")

        m = self._config.get("routing_hint_max_chars")
        if m is not None:
            try:
                m = int(m)
            except (TypeError, ValueError):
                m = None
        if m is not None and m > 0 and len(hint) > m:
            logger.info("Routing hint 超过 %d 字符，截断至 %d 字符", m, m)
            hint = hint[:m]

        self._routing_hint_cache = hint
        return hint

    def _strip_markdown_fence(self, text: str) -> str:
        """Remove optional markdown code fences wrapping JSON."""
        text = text.strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if len(lines) < 2:
            return text
        body = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(body).strip()

    def _extract_llm_text(self, response) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response.strip()
        content = getattr(response, "content", None)
        if content is not None:
            return str(content).strip()
        return str(response).strip()

    def _truncate_observation(self, observation: str) -> str:
        planner_cfg = self._config.get("planner", {})
        if not isinstance(planner_cfg, dict):
            planner_cfg = {}
        max_chars = planner_cfg.get("replan_observation_max_chars", 4000)
        if isinstance(max_chars, int) and max_chars > 0 and len(observation) > max_chars:
            return observation[:max_chars] + "…[truncated]"
        return observation

    def _parse_tool_names(self, tool_index: str) -> set:
        """Extract tool names from '- name: description' lines."""
        names: set = set()
        for line in (tool_index or "").splitlines():
            line = line.strip()
            if not line.startswith("-"):
                continue
            rest = line[1:].strip()
            if not rest:
                continue
            name = rest.split(":", 1)[0].strip() if ":" in rest else rest.split()[0]
            if name:
                names.add(name)
        return names

    def _fallback_plan(self) -> list:
        """Rule-based fallback when LLM output cannot be parsed or validated."""
        fb = self._config.get("planner", {}).get("fallback_plan")
        if isinstance(fb, list):
            return fb
        return [{
            "id": "fallback-clarify",
            "description": "Clarify the user question and retry planning with simpler retrieval steps.",
            "intent": "clarify",
        }]

    def plan(self, query: str, context: str, tool_index: str, routing_hint: str) -> list:
        """根据用户问题生成子任务规划队列。"""
        import json
        from src.libs.llm.base_llm import Message

        system_prompt = (
            "你是一个面向文档问答的 RAG-Agent 子任务规划器。"
            "根据用户问题和可用工具，将任务拆解为有序子任务列表，并以 JSON 数组形式输出。\n"
            "重要规则：\n"
            "- 只输出一段 JSON 数组，不要添加任何额外文本、解释或 Markdown 代码围栏。\n"
            "- 每个子任务对象必须包含以下键：\n"
            "  - id: 字符串，唯一标识\n"
            "  - description: 字符串，自然语言步骤说明\n"
            "  - intent: 字符串，短意图标签\n"
            "- 可选键：\n"
            "  - suggested_tool: 字符串，若推荐使用某工具，其名称必须与可用工具索引中的某个工具名称完全一致\n"
            "  - done_criteria: 字符串，完成判定说明\n"
            "  - replan_triggers: 字符串，建议触发重新规划的条件说明\n"
            "- 不要输出或猜测任何工具的 inputSchema 或具体 JSON 参数。\n"
            "- 输出必须是合法的 JSON，字符串使用双引号。"
        )

        template = self._config.get("planner", {}).get("user_prompt_template")
        if not template:
            template = (
                "用户问题：\n{query}\n\n"
                "记忆与对话摘要：\n{context}\n\n"
                "可用工具索引（仅名称与短描述，无 inputSchema）：\n{tool_index}\n\n"
                "路由启发：\n{routing_hint}"
            )
        user_prompt = template.format(
            query=query,
            context=context if context else "（无）",
            tool_index=tool_index,
            routing_hint=routing_hint if routing_hint else "（无）"
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        llm = self._get_llm()
        try:
            response = llm.chat(messages)
            text = self._extract_llm_text(response)
        except Exception as e:
            print(f"[DEBUG Planner] LLM chat failed: {e}", flush=True)
            return self._fallback_plan()

        text = self._strip_markdown_fence(text)
        print(f"[DEBUG Planner] LLM returned: {repr(text)}", flush=True)

        try:
            plan = json.loads(text)
            if not isinstance(plan, list):
                return self._fallback_plan()
        except Exception:
            return self._fallback_plan()

        available_tools = self._parse_tool_names(tool_index)

        def _validate_item(item):
            if not isinstance(item, dict):
                return False
            if "id" not in item or "description" not in item or "intent" not in item:
                return False
            if "suggested_tool" in item and item["suggested_tool"]:
                if item["suggested_tool"] not in available_tools:
                    return False
            for key in ("done_criteria", "replan_triggers"):
                if key in item and not isinstance(item[key], str):
                    if isinstance(item[key], list):
                        item[key] = "\n".join(str(x) for x in item[key])
                    else:
                        item[key] = str(item[key])
            return True

        valid_plan = []
        for item in plan:
            if not _validate_item(item):
                return self._fallback_plan()
            valid_plan.append(item)

        return valid_plan

    def replan(self, query: str, context: str, tool_index: str, routing_hint: str, observation: str) -> list:
        """根据执行观测修订或追加子任务；通过改写检索问句、换工具、补步骤改善证据。"""
        import json
        from src.libs.llm.base_llm import Message

        default_replan_system_prompt = (
            "你是一个面向文档问答的 RAG-Agent 子任务规划器，负责根据执行观测修订或追加子任务。\n"
            "重要规则：\n"
            "- 只输出一段 JSON 数组，不要添加任何额外文本、解释或 Markdown 代码围栏。\n"
            "- 每个子任务对象必须包含以下键：\n"
            "  - id: 字符串，唯一标识\n"
            "  - description: 字符串，自然语言步骤说明\n"
            "  - intent: 字符串，短意图标签\n"
            "- 可选键：\n"
            "  - suggested_tool: 字符串，若推荐使用某工具，其名称必须与可用工具索引中的某个工具名称完全一致\n"
            "  - done_criteria: 字符串，完成判定说明\n"
            "  - replan_triggers: 字符串，建议触发重新规划的条件说明\n"
            "  - retrieval_hints: 字符串数组，短句，如「改写 query 为…」「补某 doc 全文」\n"
            "- 不要输出或猜测任何工具的 inputSchema 或具体 JSON 参数。\n"
            "- 输出必须是合法的 JSON，字符串使用双引号。\n"
            "\n"
            "【replan 修订策略】\n"
            "你需要根据 '执行与评估观测' 来决定是否需要修订或追加子任务。修订时请注意：\n"
            "（a）读 observation：区分子任务级失败（某条 needs_replan）与全局终稿门禁（证据不足以回答原问题）。\n"
            "（b）换检索问句/关键词：在新子任务 description 中给出更可检索的英文术语 + 中文关键词；可改 suggested_tool 或 filters 语义（写在 description）。\n"
            "    注意：query_knowledge_hub / search_by_metadata 调用 MCP 后，问句扩写由 MCP 服务端自动完成，replan 不得输出或建议 MQE/HyDE。\n"
            "（c）换工具或补步骤：如补 get_document_full_text、search_by_metadata（收窄 doc_id）、get_neighbor_chunks 等；勿重复已失败且无新信息的同参调用。\n"
            "（d）可选任务字段：除 plan 必填键外，允许 retrieval_hints（字符串数组，短句，如「改写 query 为…」「补某 doc 全文」）——不得含 MCP arguments，不得提及 MQE/HyDE。\n"
        )
        system_prompt = self._config.get("planner", {}).get("replan_system_prompt", default_replan_system_prompt)

        template = self._config.get("planner", {}).get("replan_user_prompt_template")
        if not template:
            template = (
                "用户问题：\n{query}\n\n"
                "记忆与对话摘要：\n{context}\n\n"
                "可用工具索引（仅名称与短描述，无 inputSchema）：\n{tool_index}\n\n"
                "路由启发：\n{routing_hint}\n\n"
                "执行与评估观测：\n{observation}"
            )

        observation = self._truncate_observation(observation or "")

        user_prompt = template.format(
            query=query,
            context=context if context else "（无）",
            tool_index=tool_index,
            routing_hint=routing_hint if routing_hint else "（无）",
            observation=observation if observation else "（无）",
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        llm = self._get_llm()
        try:
            response = llm.chat(messages)
            text = self._extract_llm_text(response)
        except Exception:
            return self._fallback_plan()

        text = self._strip_markdown_fence(text)

        try:
            new_plan = json.loads(text)
            if not isinstance(new_plan, list):
                return self._fallback_plan()
        except Exception:
            return self._fallback_plan()

        available_tools = self._parse_tool_names(tool_index)

        def _validate_item(item):
            if not isinstance(item, dict):
                return False
            if "id" not in item or "description" not in item or "intent" not in item:
                return False
            if "suggested_tool" in item and item["suggested_tool"]:
                if item["suggested_tool"] not in available_tools:
                    return False
            if "retrieval_hints" in item:
                hints = item["retrieval_hints"]
                if isinstance(hints, list):
                    cleaned = []
                    for x in hints:
                        s = str(x).strip() if x else ""
                        if not s:
                            continue
                        lower = s.lower()
                        if any(forbidden in lower for forbidden in ("mqe", "hyde", "arguments")):
                            continue
                        cleaned.append(s)
                    item["retrieval_hints"] = cleaned
                else:
                    item["retrieval_hints"] = []
            for key in ("done_criteria", "replan_triggers"):
                if key in item:
                    if not isinstance(item[key], str):
                        if isinstance(item[key], list):
                            item[key] = "\n".join(str(x) for x in item[key])
                        else:
                            item[key] = str(item[key])
            return True

        valid_plan = []
        for item in new_plan:
            if not _validate_item(item):
                return self._fallback_plan()
            valid_plan.append(item)

        return valid_plan
