"""Function calling：优先 Harness Custom HTTP（原生 tools），可回退 JSON 协议 + LLMFactory。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

from harness.evaluator.tools import EvaluatorFileTools
from harness.llm_client import HarnessLLM
from harness.llm_helpers import chat, strip_json_fence
from harness.llm_http import HarnessCustomHttp, HarnessLLMHttpError, openai_tool_schemas

_JSON_FC_SUFFIX = """
## 备用 JSON 协议（仅当无法使用原生 tools 时）
需要读文件时只输出：{"tool_calls": [{"name": "read_file", "arguments": {"rel_path": "..."}}]}
完成时只输出：{"final": { ... }}
"""


def _try_parse_fc_response(text: str) -> dict[str, Any] | None:
    """尝试从 LLM 返回的文本中解析出 JSON 对象。

    支持三种格式：
    1. 纯 JSON 字符串（可能带 markdown 围栏）
    2. 文本中嵌入的 JSON 对象（正则提取）
    3. 解析失败返回 None

    Args:
        text: LLM 返回的原始文本

    Returns:
        解析出的 dict，或 None（解析失败）
    """
    raw = strip_json_fence((text or "").strip())
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """解析工具调用的参数。

    LLM 返回的 arguments 可能是 dict 或 JSON 字符串，统一转成 dict。

    Args:
        raw: 原始参数（dict、str 或其他类型）

    Returns:
        解析后的参数字典，解析失败返回空 dict
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _extract_final_from_content(content: str | None, parse_final: Callable[[dict], dict] | None) -> dict[str, Any] | None:
    """从 LLM 返回内容中提取最终结论对象。

    检查 LLM 是否输出了 final 字段或包含特定关键字（coverage、action、passed 等），
    表示已完成分析可以结束循环。

    Args:
        content: LLM 返回的文本内容
        parse_final: 可选的自定义解析函数，用于验证/转换 final 对象

    Returns:
        提取出的 final 对象，或 None（未找到有效结论）
    """
    if not content or not content.strip():
        return None
    obj = _try_parse_fc_response(content)
    if not obj:
        return None
    final = obj.get("final")
    if isinstance(final, dict):
        return parse_final(final) if parse_final else final
    if parse_final:
        try:
            return parse_final(obj)
        except Exception:
            pass
    if any(k in obj for k in ("coverage", "action", "passed", "reasons", "test_source")):
        return obj
    return None


def run_function_calling_loop(
    *,
    http: HarnessCustomHttp | None = None,
    bundle: HarnessLLM | None = None,
    system: str,
    user: str,
    tools: EvaluatorFileTools,
    harness_cfg: dict,
    agent_key: str = "evaluator",
    max_rounds: int = 8,
    parse_final: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    fc_mode: str = "auto",
    fallback_json: bool = True,
) -> dict[str, Any]:
    """多轮 function calling 主入口，支持原生 tools 和 JSON 协议两种模式。

    根据 fc_mode 选择执行策略：
    - native: 仅使用 OpenAI 原生 tools API（需要 HarnessCustomHttp）
    - json: 仅使用 JSON 协议模拟 function calling（需要 LLMFactory）
    - auto: 优先原生，失败时回退 JSON（需要至少一个可用）

    Args:
        http: 原生 API 客户端（支持 tools 参数）
        bundle: LLM 工厂客户端（用于 JSON 协议）
        system: 系统提示词
        user: 用户输入
        tools: 文件工具集（read_file、list_dir、grep_in_file）
        harness_cfg: Harness 全局配置
        agent_key: 代理标识（用于配置查找）
        max_rounds: 最大循环轮数
        parse_final: 可选的 final 对象验证函数
        fc_mode: 模式选择（native/json/auto）
        fallback_json: auto 模式下是否允许回退 JSON

    Returns:
        LLM 输出的 final 对象（经过 parse_final 验证）

    Raises:
        RuntimeError: 无可用客户端或超过最大轮数
        HarnessLLMHttpError: 原生模式下 HTTP 调用失败
    """
    mode = (fc_mode or "native").strip().lower()

    if mode == "json":
        if bundle is None:
            raise RuntimeError("fc_mode=json 需要 LLMFactory bundle")
        return _run_json_protocol_loop(
            bundle,
            system=system,
            user=user,
            tools=tools,
            harness_cfg=harness_cfg,
            agent_key=agent_key,
            max_rounds=max_rounds,
            parse_final=parse_final,
        )

    if mode == "native" and http is None:
        raise HarnessLLMHttpError(
            "原生 function calling 需要 HarnessCustomHttp。"
            "请设置 evaluator.llm_transport: custom_http，并在 harness.yaml 的 llm.base_url 填写完整 endpoint。"
        )

    if http is not None:
        try:
            return _run_native_tools_loop(
                http,
                system=system,
                user=user,
                file_tools=tools,
                harness_cfg=harness_cfg,
                agent_key=agent_key,
                max_rounds=max_rounds,
                parse_final=parse_final,
            )
        except HarnessLLMHttpError as e:
            if mode == "native" or not fallback_json or bundle is None:
                raise
            logger.warning(
                "原生 function calling 失败，回退 JSON 协议: %s",
                e,
            )
            return _run_json_protocol_loop(
                bundle,
                system=system,
                user=user,
                tools=tools,
                harness_cfg=harness_cfg,
                agent_key=agent_key,
                max_rounds=max_rounds,
                parse_final=parse_final,
            )

    if bundle is not None and (mode == "auto" or fallback_json):
        return _run_json_protocol_loop(
            bundle,
            system=system,
            user=user,
            tools=tools,
            harness_cfg=harness_cfg,
            agent_key=agent_key,
            max_rounds=max_rounds,
            parse_final=parse_final,
        )
    raise RuntimeError("function calling 需要 HarnessCustomHttp（native）或 LLMFactory（json/auto）")


def _run_native_tools_loop(
    http: HarnessCustomHttp,
    *,
    system: str,
    user: str,
    file_tools: EvaluatorFileTools,
    harness_cfg: dict,
    agent_key: str,
    max_rounds: int,
    parse_final: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    """使用 OpenAI 原生 tools API 的多轮 function calling 循环。

    流程：
    1. 发送 messages + tools 定义给 LLM
    2. LLM 返回 tool_calls → 执行工具 → 把结果作为 tool role 消息追加
    3. 重复直到 LLM 不再调用工具，而是输出 final 对象
    4. 如果 LLM 一直不输出 final，主动提示一次后继续循环

    Args:
        http: 支持原生 tools 的 HTTP 客户端
        system: 系统提示词
        user: 用户输入
        file_tools: 文件工具集
        harness_cfg: Harness 配置
        agent_key: 代理标识
        max_rounds: 最大轮数
        parse_final: final 对象验证函数

    Returns:
        LLM 输出的 final 对象

    Raises:
        RuntimeError: 超过最大轮数仍未得到 final
    """
    messages: list[dict[str, Any]] = [
        # 角色 + 任务规则 + 最终要输出的 JSON 格式；三个文件工具的文字说明（read_file 等
        {"role": "system", "content": system.rstrip() + "\n\n" + file_tools.schema_for_prompt()},
        # 本轮具体任务的数据（子任务、索引、草稿、pytest 失败等）
        {"role": "user", "content": user},
    ]
    # 生成一份发给 LLM API 的「工具清单」（OpenAI Chat Completions 格式的 tools 数组），告诉模型它可以调用哪些函数、每个函数要什么参数
    tool_defs = openai_tool_schemas()

    # 追踪连续只调用 read_file 的轮次
    consecutive_read_only = 0
    # 连续 read_file 超过此阈值时，强制停止
    READ_ONLY_THRESHOLD = 5

    for round_i in range(max_rounds):
        logger.info("[FC native] round %d/%d - calling LLM...", round_i + 1, max_rounds)

        # 判断是否需要强制 LLM 输出结论
        remaining = max_rounds - round_i - 1
        force_final = (remaining == 0) or (consecutive_read_only >= READ_ONLY_THRESHOLD)

        if force_final:
            # 不提供工具，强制输出结论
            reason = "last round" if remaining == 0 else f"consecutive read_file x{consecutive_read_only}"
            logger.info("[FC native] round %d - forcing final (%s)", round_i + 1, reason)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "请立即根据已读取的信息输出最终结论 JSON（包含 final 字段）。"
                        "不要再调用任何工具。基于已有信息给出最佳判断。"
                    ),
                }
            )
            data = http.chat_completions(
                messages,
                harness_cfg=harness_cfg,
                agent_key=agent_key,
                tools=None,
                tool_choice=None,
            )
        else:
            data = http.chat_completions(
                messages,
                harness_cfg=harness_cfg,
                agent_key=agent_key,
                tools=tool_defs,
                tool_choice="auto",
            )

        # 从响应取出 choices[0].message，看有没有 tool_calls
        msg = http._choice_message(data)
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            names = [str((tc.get("function") or {}).get("name", "?")) for tc in tool_calls]
            logger.info("[FC native] round %d - tool_calls: %s", round_i + 1, names)

            # 检测是否全部是 read_file 调用
            if all(n == "read_file" for n in names):
                consecutive_read_only += 1
            else:
                consecutive_read_only = 0

            # 如果有 tool_calls，说明模型认为需要调用工具来完成任务，把 tool_calls 追加到 messages 列表
            messages.append(msg)
            for tc in tool_calls:
                fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                # 从 tool_calls 中取出每个工具的名称和参数
                name = str(fn.get("name", ""))
                args = _parse_tool_arguments(fn.get("arguments"))
                result = file_tools.execute(name, args)
                # 调用文件工具，执行工具的实际操作（读文件、列目录、搜索文件等），得到执行结果
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tc.get("id", "")),
                        "content": result,
                    }
                )
            # 把执行结果作为 tool role 消息追加到 messages 列表，表示模型已经执行了工具调用，并得到了结果
            continue
        # 如果没有 tool_calls，说明模型认为任务已经完成，可以输出最终结论

        content = msg.get("content")
        # 从响应取出 content 字段，表示模型输出的文本内容
        parsed = _extract_final_from_content(
            content if isinstance(content, str) else str(content or ""),
            parse_final,
        )
        # 尝试从文本内容中提取最终结论对象
        if parsed is not None:
            logger.info("[FC native] round %d - got final: %s", round_i + 1, str(parsed)[:200])
            # 如果提取成功，返回最终结论对象
            return parsed
        # 如果提取失败，把当前消息追加到 messages 列表，表示模型需要继续执行任务
        logger.warning("[FC native] round %d - no valid final, prompting again...", round_i + 1)

        messages.append(msg)
        # 追加一条用户消息，提示模型输出最终结论
        messages.append(
            {
                "role": "user",
                "content": (
                    "请输出最终结论。若已完成分析，在回复 JSON 中包含 final 字段，"
                    '例如 {"final": {"coverage": "complete", "action": "skip", "reasons": "..."}}'
                ),
            }
        )
    # 如果超过最大轮数仍未得到有效 final，抛出错误
    raise RuntimeError(f"原生 function calling 超过最大轮数 ({max_rounds})")


def _run_json_protocol_loop(
    bundle: HarnessLLM,
    *,
    system: str,
    user: str,
    tools: EvaluatorFileTools,
    harness_cfg: dict,
    agent_key: str,
    max_rounds: int,
    parse_final: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    """使用 JSON 协议模拟 function calling 的多轮循环。

    适用于不支持原生 tools API 的 LLM。通过约定的 JSON 格式实现工具调用：
    - LLM 输出 {"tool_calls": [...]} 表示要调用工具
    - LLM 输出 {"final": {...}} 表示完成分析

    流程：
    1. 在 system prompt 中说明 JSON 协议格式
    2. LLM 返回 JSON → 解析 tool_calls → 执行工具 → 把结果拼到 user 消息
    3. 重复直到 LLM 输出 final 对象
    4. 如果 LLM 输出格式错误，提示重新输出

    Args:
        bundle: LLM 工厂客户端
        system: 系统提示词
        user: 用户输入
        tools: 文件工具集
        harness_cfg: Harness 配置
        agent_key: 代理标识
        max_rounds: 最大轮数
        parse_final: final 对象验证函数

    Returns:
        LLM 输出的 final 对象

    Raises:
        RuntimeError: 超过最大轮数仍未得到有效 final
    """
    system_full = system.rstrip() + "\n\n" + tools.schema_for_prompt() + _JSON_FC_SUFFIX
    conversation = user
    last_obj: dict[str, Any] | None = None

    for round_i in range(max_rounds):
        logger.info("[FC json] round %d/%d - calling LLM...", round_i + 1, max_rounds)
        raw = chat(
            bundle,
            system=system_full,
            user=conversation,
            harness_cfg=harness_cfg,
            agent_key=agent_key,
        )
        obj = _try_parse_fc_response(raw)
        if obj is None:
            logger.warning("[FC json] round %d - failed to parse JSON, retrying", round_i + 1)
            conversation = (
                f"{user}\n\n---\n请严格输出 JSON：tool_calls 或 final。\n上轮节选：\n{raw[:2000]}"
            )
            continue

        last_obj = obj
        if obj.get("tool_calls"):
            calls = obj["tool_calls"]
            if not isinstance(calls, list):
                calls = [calls]
            names = [str(c.get("name", "?")) for c in calls]
            logger.info("[FC json] round %d - tool_calls: %s", round_i + 1, names)
            tool_result = tools.execute_batch(calls)
            conversation = (
                f"{user}\n\n## 第 {round_i + 1} 轮工具结果\n{tool_result}\n\n"
                "请继续：tool_calls 或 final。"
            )
            continue

        final = obj.get("final")
        if isinstance(final, dict):
            logger.info("[FC json] round %d - got final: %s", round_i + 1, str(final)[:200])
            return parse_final(final) if parse_final else final

        if parse_final:
            try:
                return parse_final(obj)
            except Exception:
                pass
        if any(k in obj for k in ("coverage", "action", "passed", "reasons", "test_source")):
            return obj

        conversation = (
            f"{user}\n\n---\n请输出 final 或 tool_calls。\n"
            f"{json.dumps(obj, ensure_ascii=False)[:1500]}"
        )

    if last_obj and parse_final:
        try:
            return parse_final(last_obj)
        except Exception:
            pass
    raise RuntimeError(f"JSON function calling 超过最大轮数 ({max_rounds})")
