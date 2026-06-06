"""一次性脚本：按 test_outline.md 生成 test_*.py。可重复运行覆盖骨架。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent

# (relative_path, doc_id, pytestmark, body)
FILES: list[tuple[str, str, str, str]] = [
    # --- contracts ---
    (
        "contracts/test_mcp_normalized.py",
        "1.1",
        "pytestmark = [pytest.mark.unit]",
        '''"""阶段 1.1 — MCP 归一化 dict 契约。"""
import pytest
from test.helpers.contracts import assert_mcp_normalized
from test.helpers.samples import sample_mcp_raw_error, sample_mcp_raw_multimodal, sample_mcp_raw_text_only

pytestmark = [pytest.mark.unit]


def test_text_block_shape():
    assert_mcp_normalized(sample_mcp_raw_text_only())


def test_image_block_shape():
    assert_mcp_normalized(sample_mcp_raw_multimodal())


def test_is_error_bool():
    raw = sample_mcp_raw_error()
    assert raw["isError"] is True
    assert_mcp_normalized(raw)
''',
    ),
    (
        "contracts/test_eval_result.py",
        "1.2",
        "",
        '''"""阶段 1.2 — EvalResult 契约。"""
import pytest
from test.helpers.contracts import assert_eval_result
from test.helpers.samples import sample_eval_result

pytestmark = [pytest.mark.unit]


def test_ok_shape():
    assert_eval_result(sample_eval_result())


def test_needs_replan_implies_not_passed():
    assert_eval_result(sample_eval_result(passed=False, status="needs_replan"))
''',
    ),
    (
        "contracts/test_subtask_result.py",
        "1.3",
        "",
        '''"""阶段 1.3 — SubtaskResult 契约。"""
import pytest
from test.helpers.contracts import assert_subtask_result
from test.helpers.samples import sample_subtask_result

pytestmark = [pytest.mark.unit]


def test_minimal_shape():
    assert_subtask_result(sample_subtask_result())


def test_needs_replan_status():
    assert_subtask_result(sample_subtask_result(status="needs_replan", observation_for_replan="retry"))
''',
    ),
    (
        "contracts/test_next_action_result.py",
        "1.4",
        "",
        '''"""阶段 1.4 — NextActionResult 契约。"""
import pytest
from test.helpers.contracts import assert_next_action_result

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "action,tool_name",
    [
        ("stop", None),
        ("replan", None),
        ("call_tool", "query_knowledge_hub"),
    ],
)
def test_action_enum(action, tool_name):
    payload = {"action": action}
    if tool_name:
        payload["tool_name"] = tool_name
    assert_next_action_result(payload)
''',
    ),
    (
        "contracts/test_global_readiness.py",
        "1.5",
        "",
        '''"""阶段 1.5 — GlobalAnswerReadiness 契约。"""
import pytest
from test.helpers.contracts import assert_global_answer_readiness
from test.helpers.samples import sample_global_readiness

pytestmark = [pytest.mark.unit]


def test_sufficient():
    assert_global_answer_readiness(sample_global_readiness())


def test_need_replan_observation_non_empty():
    assert_global_answer_readiness(
        sample_global_readiness(sufficient_for_answer=False, need_replan=True, observation_for_replan="gap")
    )
''',
    ),
    (
        "contracts/test_answer_result.py",
        "1.6",
        "",
        '''"""阶段 1.6 — AnswerResult 契约。"""
import pytest
from test.helpers.contracts import assert_answer_result
from test.helpers.samples import sample_answer_result

pytestmark = [pytest.mark.unit]


def test_text_and_images():
    assert_answer_result(sample_answer_result())


def test_text_only():
    assert_answer_result(sample_answer_result(images=[]))
''',
    ),
]

# Unit / integration / e2e templates: (path, id, mark, class_name, tests_body)
UNIT_SPECS = [
    ("unit/test_memory_evidence_body.py", "2.1.1", "unit", "MemoryManager._evidence_body", "memory_manager", [
        ('text_snippet_preferred', 'assert mm._evidence_body({"text_snippet": "a", "text": "b"}) == "a"'),
        ('fallback_text', 'assert mm._evidence_body({"text": "only"}) == "only"'),
        ('empty_returns_empty', 'assert mm._evidence_body({}) == ""'),
    ]),
    ("unit/test_memory_evidence_chunks_from_result.py", "2.1.2", "unit", "MemoryManager._evidence_chunks_from_result", "memory_manager", [
        ('multiple_citations', 'r = {"citations": [{"text_snippet": "x", "chunk_id": "1"}]}; out = mm._evidence_chunks_from_result(r); assert len(out) == 1'),
        ('top_level_text_when_no_citations', 'out = mm._evidence_chunks_from_result({"text": "body"}); assert len(out) == 1 and out[0]["text_snippet"] == "body"'),
        ('empty_result', 'assert mm._evidence_chunks_from_result({}) == []'),
    ]),
    ("unit/test_generator_collect_images_from_raw.py", "2.2.1", "unit", "Generator._collect_images_from_raw", "generator", [
        ('from_content', 'imgs = gen._collect_images_from_raw(mock_mcp_raw_multimodal); assert len(imgs) >= 1'),
        ('skip_empty_data', 'raw = {"content": [{"type": "image", "data": "", "mimeType": "image/png"}]}; assert gen._collect_images_from_raw(raw) == []'),
    ]),
    ("unit/test_generator_summarize_mcp_result.py", "2.2.2", "unit", "Generator.summarize_mcp_result", "generator", [
        ('concat_text_only', 's = gen.summarize_mcp_result(mock_mcp_raw_text); assert "hello" in s'),
        ('error_prefix', 's = gen.summarize_mcp_result(mock_mcp_raw_error); assert "[error]" in s'),
        ('image_placeholder', 's = gen.summarize_mcp_result(mock_mcp_raw_multimodal); assert "图" in s or "image" in s.lower()'),
    ]),
    ("unit/test_generator_format_trace.py", "2.2.3", "unit", "Generator._format_trace", "generator", [
        ('empty_placeholder', 's = gen._format_trace([]); assert s'),
        ('formats_tool_and_summary', 's = gen._format_trace([{"tool_name": "t", "summary": "ok"}]); assert "t" in s and "ok" in s'),
    ]),
    ("unit/test_evaluator_to_planner_observation.py", "2.3.1", "unit", "Evaluator.to_planner_observation", "evaluator", [
        ('includes_status', 'from test.helpers.samples import sample_eval_result; obs = ev.to_planner_observation(sample_eval_result(status="needs_replan")); assert obs'),
    ]),
    ("unit/test_orchestrator_build_final_evidence_bundle.py", "2.4.1", "unit", "RagOrchestrator._build_final_evidence_bundle", "orchestrator", [
        ('sorted_by_task_id', 'from test.helpers.samples import sample_subtask_result; b = orch._build_final_evidence_bundle([sample_subtask_result(task_id="b"), sample_subtask_result(task_id="a")]); assert "a" in b and "b" in b'),
    ]),
    ("unit/test_orchestrator_merge_subtask_images.py", "2.4.2", "unit", "RagOrchestrator._merge_subtask_images", "orchestrator", [
        ('dedupe_by_data', 'from test.helpers.samples import sample_answer_result; img = sample_answer_result()["images"][0]; merged = orch._merge_subtask_images([[img], [img]]); assert len(merged) == 1'),
    ]),
    ("unit/test_orchestrator_should_attach_images.py", "2.4.3", "unit", "RagOrchestrator._should_attach_images", "orchestrator", [
        ('no_images_false', 'assert orch._should_attach_images([], "query") is False'),
    ]),
    ("unit/test_orchestrator_build_tool_index_text.py", "2.4.4", "unit", "RagOrchestrator.build_tool_index_text", "orchestrator", [
        ('lists_all_tools', 'orch._tools_by_name = {"a": {"description": "d"}}; t = orch.build_tool_index_text(); assert "- a:" in t'),
    ]),
    ("unit/test_planner_load_routing_hint.py", "2.5.1", "unit", "PlannerAgent.load_routing_hint", "planner_agent", [
        ('cache_second_call', 'if not hasattr(planner_agent, "load_routing_hint"): pytest.skip("not implemented"); h1 = planner_agent.load_routing_hint(); h2 = planner_agent.load_routing_hint(); assert h1 == h2'),
    ]),
    ("unit/test_executor_fill_arguments.py", "3.1", "unit", "Executor.fill_arguments", "executor", [
        ('valid_json', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_planner_plan.py", "3.2", "unit", "PlannerAgent.plan", "planner_agent", [
        ('parses_json_array', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_planner_replan.py", "3.3", "unit", "PlannerAgent.replan", "planner_agent", [
        ('includes_observation', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_evaluator_evaluate.py", "3.4", "unit", "Evaluator.evaluate", "evaluator", [
        ('five_keys', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_evaluator_quick_rule_check.py", "3.5", "unit", "Evaluator.quick_rule_check", "evaluator", [
        ('consecutive_errors_hard_fail', 'pytest.skip("implement")'),
    ]),
    ("unit/test_generator_choose_next_action.py", "3.6", "unit", "Generator.choose_next_action", "generator", [
        ('action_enum', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_generator_draft_partial_answer.py", "3.7", "unit", "Generator.draft_partial_answer", "generator", [
        ('returns_str', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_orchestrator_check_global_answer_readiness.py", "3.8", "unit", "RagOrchestrator._check_global_answer_readiness", "orchestrator", [
        ('five_keys', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_orchestrator_synthesize_final_answer.py", "3.9", "unit", "RagOrchestrator._synthesize_final_answer", "orchestrator", [
        ('returns_str', 'pytest.skip("implement with mock LLM")'),
    ]),
    ("unit/test_executor_init.py", "3.10", "unit", "Executor.__init__", "executor", [
        ('holds_mcp_client', 'assert hasattr(executor, "_mcp_client") or hasattr(executor, "mcp_client")'),
    ]),
    ("unit/test_planner_init.py", "3.11", "unit", "PlannerAgent.__init__", "planner_agent", [
        ('constructs', 'assert planner_agent is not None'),
    ]),
    ("unit/test_evaluator_init.py", "3.12", "unit", "Evaluator.__init__", "evaluator", [
        ('constructs', 'assert evaluator is not None'),
    ]),
    ("unit/test_generator_init.py", "3.13", "unit", "Generator.__init__", "generator", [
        ('inner_state', 'assert hasattr(gen, "_inner_trace") or hasattr(gen, "reset_subtask_state")'),
    ]),
    ("unit/test_mcp_client_init.py", "4.1", "unit", "McpClient.__init__", "mcp_client", [
        ('stores_session', 'assert mcp_client is not None'),
    ]),
    ("unit/test_mcp_client_call_tool.py", "4.2", "unit", "McpClient.call_tool", "mcp_client", [
        ('normalized_shape', 'pytest.skip("implement call_tool + assert_mcp_normalized")'),
    ]),
    ("unit/test_executor_call_tool.py", "4.3", "unit", "Executor.call_tool", "executor", [
        ('retry', 'pytest.skip("implement with mock")'),
    ]),
    ("unit/test_executor_execute_task.py", "4.4", "unit", "Executor.execute_task", "executor", [
        ('fill_then_call', 'pytest.skip("implement with mock")'),
    ]),
    ("unit/test_memory_manager_init.py", "5.1", "unit", "MemoryManager.__init__", "memory_manager", [
        ('short_term_empty', 'assert mm.short_term == []'),
    ]),
    ("unit/test_memory_compute_similarity.py", "5.2", "unit", "MemoryManager.compute_memory_similarity", "memory_manager", [
        ('empty_chunks', 'score, embs = mm.compute_memory_similarity([], "q"); assert score == 0.0 or score is not None'),
    ]),
    ("unit/test_memory_add_short_term.py", "5.3", "unit", "MemoryManager.add_short_term", "memory_manager", [
        ('adds_item', 'mm.add_short_term("q", {"text": "a"}); assert len(mm.short_term) >= 1'),
    ]),
    ("unit/test_memory_update_access_count.py", "5.4", "unit", "MemoryManager.update_access_count", "memory_manager", [
        ('increments', 'item = {"access_count": 0}; mm.update_access_count(item); assert item.get("access_count", 0) >= 1'),
    ]),
    ("unit/test_memory_compress_memory.py", "5.5", "unit", "MemoryManager.compress_memory", "memory_manager", [
        ('returns_tuple', 'pytest.skip("mock LLM")'),
    ]),
    ("unit/test_memory_compress_short_term.py", "5.6", "unit", "MemoryManager.compress_short_term", "memory_manager", [
        ('returns_str', 'pytest.skip("mock LLM")'),
    ]),
    ("unit/test_memory_condition_fn.py", "5.7", "unit", "MemoryManager.condition_fn", "memory_manager", [
        ('threshold', 'pytest.skip("need memory_item fixture")'),
    ]),
    ("unit/test_memory_delete_short_term.py", "5.8", "unit", "MemoryManager.delete_short_term", "memory_manager", [
        ('removes', 'pytest.skip("implement")'),
    ]),
    ("unit/test_memory_promote_to_long_term.py", "5.9", "unit", "MemoryManager.promote_to_long_term", "memory_manager", [
        ('promote', 'pytest.skip("mock Chroma")'),
    ]),
    ("unit/test_memory_get_relevant.py", "5.10", "unit", "MemoryManager.get_relevant", "memory_manager", [
        ('top_k', 'pytest.skip("mock encode")'),
    ]),
    ("unit/test_memory_retrieve_context.py", "5.11", "unit", "MemoryManager.retrieve_context", "memory_manager", [
        ('returns_str', 'ctx = mm.retrieve_context("q"); assert isinstance(ctx, str)'),
    ]),
    ("unit/test_memory_add_event.py", "5.12", "integration", "MemoryManager.add_event", "memory_manager", [
        ('dual_write', 'pytest.skip("tmp DB")'),
    ]),
    ("unit/test_memory_query_relevant_events.py", "5.13", "unit", "MemoryManager.query_relevant_events", "memory_manager", [
        ('session_filter', 'pytest.skip("mock Qdrant")'),
    ]),
    ("unit/test_context_manager_init.py", "6.1", "unit", "ContextManager.__init__", "context_manager", [
        ('empty_window', 'assert cm.context_window == []'),
    ]),
    ("unit/test_context_update_context.py", "6.2", "unit", "ContextManager.update_context", "context_manager", [
        ('appends', 'cm.update_context("q", "a", session_id="s"); assert len(cm.context_window) == 1'),
    ]),
    ("unit/test_context_get_context_window.py", "6.3", "unit", "ContextManager.get_context_window", "context_manager", [
        ('recent_n', 'cm.update_context("q", "a"); w = cm.get_context_window(1); assert len(w) <= 1'),
    ]),
    ("unit/test_context_get_relevant_context.py", "6.4", "unit", "ContextManager.get_relevant_context", "context_manager", [
        ('returns_str', 'pytest.skip("mock encode+LLM")'),
    ]),
    ("unit/test_generator_reset_subtask_state.py", "7.1", "unit", "Generator.reset_subtask_state", "generator", [
        ('clears', 'gen.reset_subtask_state(); assert gen._inner_trace == []'),
    ]),
    ("unit/test_generator_run_subtask.py", "7.2", "integration", "Generator.run_subtask", "generator", [
        ('subtask_result_keys', 'pytest.skip("mock Executor+Evaluator")'),
    ]),
    ("unit/test_orchestrator_init.py", "8.1.1", "unit", "RagOrchestrator.__init__", "orchestrator", [
        ('constructs', 'assert orchestrator is not None'),
    ]),
    ("unit/test_orchestrator_ensure_tools_cache.py", "8.1.2", "integration", "RagOrchestrator._ensure_tools_cache", "orchestrator", [
        ('idempotent', 'pytest.skip("async mock session")'),
    ]),
    ("unit/test_orchestrator_get_input_schema.py", "8.1.3", "unit", "RagOrchestrator.get_input_schema", "orchestrator", [
        ('from_cache', 'orch._tools_by_name = {"t": {"inputSchema": {"type": "object"}}}; assert orch.get_input_schema("t")'),
    ]),
]

INTEGRATION = [
    ("integration/test_mcp_query_knowledge_hub_live.py", "4.5", "mcp", "query_knowledge_hub 真调用", [
        ('live_call', 'pytest.skip("requires MCP stdio")'),
    ]),
    ("integration/test_orchestrator_build_final_evidence_bundle_integration.py", "8.2.1", "integration", "证据包集成", [
        ('real_subtask_results', 'pytest.skip("use real SubtaskResult list")'),
    ]),
    ("integration/test_scenario_i1_subtask_inner_loop.py", "9.1", "integration", "I1 子任务内循环", [('trace_and_stop', 'pytest.skip("")')]),
    ("integration/test_scenario_i2_subtask_needs_replan.py", "9.2", "integration", "I2 needs_replan", [('replan_obs', 'pytest.skip("")')]),
    ("integration/test_scenario_i3_global_gate_replan.py", "9.3", "integration", "I3 全局门禁", [('no_synth', 'pytest.skip("")')]),
    ("integration/test_scenario_i4_global_gate_pass.py", "9.4", "integration", "I4 门禁通过", [('synth', 'pytest.skip("")')]),
    ("integration/test_scenario_i5_multimodal.py", "9.5", "integration", "I5 多模态", [('images', 'pytest.skip("")')]),
    ("integration/test_scenario_i6_citations_chain.py", "9.6", "integration", "I6 citations", [('chain', 'pytest.skip("")')]),
    ("integration/test_scenario_i7_session_consistent.py", "9.7", "integration", "I7 session", [('sid', 'pytest.skip("")')]),
    ("integration/test_scenario_i8_mcp_session_closed.py", "9.8", "integration", "I8 MCP 关闭", [('negative', 'pytest.skip("")')]),
]

E2E = [
    ("e2e/test_answer_happy_path.py", "8.3.1", "e2e", "Happy path", [('happy', 'pytest.skip("full stack")')]),
    ("e2e/test_answer_subtask_needs_replan.py", "8.3.2", "e2e", "子任务 replan", [('replan', 'pytest.skip("")')]),
    ("e2e/test_answer_global_replan.py", "8.3.3", "e2e", "全局 replan", [('global', 'pytest.skip("")')]),
    ("e2e/test_answer_global_replan_exhausted.py", "8.3.4", "e2e", "轮次用尽", [('exhausted', 'pytest.skip("")')]),
    ("e2e/test_answer_memory_context_writeback.py", "8.3.5", "e2e", "写回记忆", [('writeback', 'pytest.skip("")')]),
    ("e2e/test_answer_multimodal.py", "8.3.6", "e2e", "多模态", [('mm', 'pytest.skip("")')]),
    ("e2e/test_answer_mcp_session_closed.py", "8.3.7", "e2e", "MCP 生存期", [('closed', 'pytest.skip("")')]),
]

NONFUNC = [
    ("nonfunctional/test_config_load.py", "10.1", "unit", "配置加载", [('loads', 'from test.helpers.imports import load_config; cfg = load_config(); assert "llm" in cfg or "rag_agent" in cfg')]),
    ("nonfunctional/test_truncation_limits.py", "10.2", "unit", "截断", [('limits', 'pytest.skip("implement")')]),
    ("nonfunctional/test_logging_on_failures.py", "10.3", "unit", "日志", [('log', 'pytest.skip("caplog")')]),
    ("nonfunctional/test_llm_live_sample.py", "10.4", "llm_live", "真实 LLM", [('live', 'pytest.skip("local only")')]),
]


def _fixture_params(primary: str, body: str) -> str:
    names = [primary]
    if "mock_mcp_raw" in body:
        for n in ("mock_mcp_raw_text", "mock_mcp_raw_multimodal", "mock_mcp_raw_error"):
            if n not in names:
                names.append(n)
    if "mcp_client" in body and primary != "mcp_client" and "mcp_client" not in names:
        names.append("mcp_client")
    return ", ".join(names)


def _unit_file(path: str, doc_id: str, mark: str, target: str, fixture: str, tests: list[tuple[str, str]]) -> str:
    var = fixture
    lines = [
        f'"""阶段 {doc_id} — {target}。见 docs/test_outline.md"""',
        "import pytest",
        "",
        f"pytestmark = [pytest.mark.{mark}]",
        "",
    ]
    for name, body in tests:
        body_use = (
            body.replace("mm.", f"{var}.")
            .replace("cm.", f"{var}.")
            .replace("pl.", f"{var}.")
            .replace("ev.", f"{var}.")
            .replace("gen.", f"{var}.")
            .replace("orch.", f"{var}.")
        )
        params = _fixture_params(fixture, body)
        lines.append(f"def test_{name}({params}):")
        lines.append(f"    {body_use}")
        lines.append("")
    return "\n".join(lines)


def _simple_file(path: str, doc_id: str, mark: str, title: str, tests: list[tuple[str, str]]) -> str:
    lines = [
        f'"""阶段 {doc_id} — {title}。见 docs/test_outline.md"""',
        "import pytest",
        "",
        f"pytestmark = [pytest.mark.{mark}]",
        "",
    ]
    for name, body in tests:
        lines.append(f"def test_{name}():")
        lines.append(f"    {body}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    for rel, _id, _mark, content in FILES:
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    for path, doc_id, mark, target, fixture, tests in UNIT_SPECS:
        content = _unit_file(path, doc_id, mark, target, fixture, tests)
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    for path, doc_id, mark, title, tests in INTEGRATION + E2E + NONFUNC:
        content = _simple_file(path, doc_id, mark, title, tests)
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    print(f"Generated {len(FILES) + len(UNIT_SPECS) + len(INTEGRATION) + len(E2E) + len(NONFUNC)} files under {ROOT}")


if __name__ == "__main__":
    main()
