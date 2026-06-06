# 测试索引（TEST_INDEX）

> **Harness / LLM 维护**：每个 `test_*` 函数对应「被测类 + 被测符号」；**`task_id` 以 `gate.` 开头**为门禁汇总行（见 `config/harness.yaml` → `milestones`）。
> Harness 向 LLM 提供**完整本表**作目录；LLM/程序**只打开表中与本任务对应的 test_file**，且只读表中列出的 `test_function` 片段，勿加载其它测试文件全文。
> 新增 / 删除 / 重命名测试文件或函数后，**必须同步更新本文件**。

## 索引表

| test_file | test_function | target_class | target_symbol | task_id | status |
|-----------|---------------|--------------|---------------|---------|--------|
| test/contracts | _gate | ContractGate | all | gate.1 | active |
| test/e2e | _gate | RagOrchestrator | answer_e2e | gate.e2e | active |
| test/gates/test_gate_context.py | test_empty_window_on_init | ContextManager | gate | replan-contextmanager-test-coverage | active |
| test/gates/test_gate_context.py | test_get_relevant_context | ContextManager | gate | replan-contextmanager-test-coverage | active |
| test/gates/test_gate_context.py | test_update_and_get_window | ContextManager | gate | replan-contextmanager-test-coverage | active |
| test/gates/test_gate_evaluator.py | test_evaluator_init | Evaluator | gate | gate.6 | active |
| test/gates/test_gate_evaluator.py | test_evaluate_returns_eval_result | Evaluator | gate | gate.6 | active |
| test/gates/test_gate_evaluator.py | test_quick_rule_check_hard_fail | Evaluator | gate | gate.6 | active |
| test/gates/test_gate_evaluator.py | _gate | Evaluator | gate | gate.6 | active |
| test/gates/test_gate_generator.py | _gate | Generator | gate | gate.7 | active |
| test/gates/test_gate_mcp.py | _gate | McpClient | gate | gate.4 | active |
| test/gates/test_gate_memory.py | _gate | MemoryManager | gate | gate.2 | active |
| test/gates/test_gate_orchestrator.py | _gate | RagOrchestrator | gate | gate.8 | active |
| test/gates/test_gate_planner.py | _gate | PlannerAgent | gate | gate.5 | active |
| test/integration | _gate | RagOrchestrator | scenario_regression | gate.8.integration | active |
| test/unit/test_(replan)_fix.py | test_empty_observation_does_not_crash | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_includes_observation_in_user_prompt | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_output_does_not_contain_input_schema | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_replan_items_have_required_keys | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_replan_method_exists_on_planner | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_replan_returns_list_of_dicts | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_replan_with_realistic_subtask_data | (replan) | fix | replan-60 | active |
| test/unit/test_(replan)_fix.py | test_truncates_long_observation | (replan) | fix | replan-60 | active |
| test/unit/test_context_get_context_window.py | test_recent_n | ContextManager | get_context_window | 2.3 | active |
| test/unit/test_context_get_relevant_context.py | test_context_window_n_config_used | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_cosine_similarity_zero_norm | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_encoder_failure_skips_entry | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_fallback_truncation_respects_length | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_get_relevant_context_top_k_zero_or_negative_returns_empty | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_llm_compression_sends_system_prompt | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_llm_failure_falls_back_to_raw_concat | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_no_query_emb_falls_back_to_most_recent | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_returns_str | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_top_k_selection_respects_cosine_similarity | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_get_relevant_context.py | test_truncation_length_applied_on_successful_compression | ContextManager | get_relevant_context | replan-context-get_relevant_context-test-fix | active |
| test/unit/test_context_manager_init.py | test_empty_window | ContextManager | __init__ | replan-context-init | active |
| test/unit/test_context_update_context.py | test_appends | ContextManager | update_context | 2.2 | active |
| test/unit/test_evaluator_evaluate.py | test_evaluate_empty_trace_retrieve_forces_more_tools | Evaluator | evaluate | 5.3 | active |
| test/unit/test_evaluator_evaluate.py | test_evaluate_strict_json_invalid_returns_failed_shape | Evaluator | evaluate | 5.3 | active |
| test/unit/test_evaluator_evaluate.py | test_five_keys | Evaluator | evaluate | 5.3 | active |
| test/unit/test_evaluator_init.py | test_constructs | Evaluator | __init__ | 5.1 | active |
| test/unit/test_evaluator_quick_rule_check.py | test_consecutive_errors_hard_fail | Evaluator | quick_rule_check | 5.2 | active |
| test/unit/test_evaluator_to_planner_observation.py | test_includes_status | Evaluator | to_planner_observation | 5.4 | active |
| test/unit/test_evaluator_to_planner_observation.py | test_truncates_long_observation | Evaluator | to_planner_observation | 5.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_invalid_arguments | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_invalid_name | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_max_retries_zero_failure | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_max_retries_zero_success | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_preserves_extra_result_keys | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_result_none_normalized | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_result_string_normalized | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_call_tool_retry_backoff_with_different_base | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_call_tool.py | test_retry | Executor | call_tool | 3.4 | active |
| test/unit/test_executor_execute_task.py | test_fill_then_call | Executor | execute_task | 3.6 | active |
| test/unit/test_executor_fill_arguments.py | test_valid_json | Executor | fill_arguments | 3.5 | active |
| test/unit/test_executor_init.py | test_all_three_attributes_present_after_init | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_both_mcp_and_config_stored_simultaneously | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_config_none_yields_empty_dict | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_config_omitted_yields_empty_dict | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_fixture_mcp_not_none | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_llm_created_and_non_null | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_llm_creation_method_exists | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_llm_creation_uses_internal_factory_not_injected | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_llm_has_chat_method | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_stores_config_dict | Executor | __init__ | 3.3 | active |
| test/unit/test_executor_init.py | test_stores_mcp_client_as_mcp | Executor | __init__ | 3.3 | active |
| test/unit/test_generator_choose_next_action.py | test_action_enum | Generator | choose_next_action |  | active |
| test/unit/test_generator_collect_images_from_raw.py | test_from_content | Generator | _collect_images_from_raw |  | active |
| test/unit/test_generator_collect_images_from_raw.py | test_skip_empty_data | Generator | _collect_images_from_raw |  | active |
| test/unit/test_generator_draft_partial_answer.py | test_returns_str | Generator | draft_partial_answer |  | active |
| test/unit/test_generator_format_trace.py | test_empty_placeholder | Generator | _format_trace |  | active |
| test/unit/test_generator_format_trace.py | test_formats_tool_and_summary | Generator | _format_trace |  | active |
| test/unit/test_generator_init.py | test_inner_state | Generator | __init__ |  | active |
| test/unit/test_generator_reset_subtask_state.py | test_clears | Generator | reset_subtask_state |  | active |
| test/unit/test_generator_run_subtask.py | test_subtask_result_keys | Generator | run_subtask | gate.7.1 | active |
| test/unit/test_generator_run_subtask.py | test_subtask_result_keys | Generator | run_subtask |  | active |
| test/unit/test_generator_summarize_mcp_result.py | test_concat_text_only | Generator | summarize_mcp_result |  | active |
| test/unit/test_generator_summarize_mcp_result.py | test_error_prefix | Generator | summarize_mcp_result |  | active |
| test/unit/test_generator_summarize_mcp_result.py | test_image_placeholder | Generator | summarize_mcp_result |  | active |
| test/unit/test_mcp_client_call_tool.py | test_normalized_shape | McpClient | call_tool | 3.2 | active |
| test/unit/test_mcp_client_init.py | test_both_session_and_config_stored_simultaneously | McpClient | __init__ | 3.1 | active |
| test/unit/test_mcp_client_init.py | test_config_defaults_to_empty_dict_when_omitted | McpClient | __init__ | 3.1 | active |
| test/unit/test_mcp_client_init.py | test_config_none_yields_empty_dict | McpClient | __init__ | 3.1 | active |
| test/unit/test_mcp_client_init.py | test_fixture_stores_config_as_dict | McpClient | __init__ | 3.1 | active |
| test/unit/test_mcp_client_init.py | test_fixture_stores_session | McpClient | __init__ | 3.1 | active |
| test/unit/test_mcp_client_init.py | test_stores_config_dict | McpClient | __init__ | 3.1 | active |
| test/unit/test_mcp_client_init.py | test_stores_underlying_session | McpClient | __init__ | 3.1 | active |
| test/unit/test_memory_add_event.py | test_dual_write | MemoryManager | add_event | 1.14 | active |
| test/unit/test_memory_add_short_term.py | test_adds_item | MemoryManager | add_short_term | replan-1.5 | active |
| test/unit/test_memory_compress_memory.py | test_returns_tuple | MemoryManager | compress_memory | 1.7 | active |
| test/unit/test_memory_compress_short_term.py | test_citation_non_dict_skipped | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_citations_with_mixed_text_fields | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_empty_list_none_returns_empty_str | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_fallback_sorts_by_score_desc_when_llm_fails | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_item_text_fallback_after_evidence_body_empty | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_item_with_top_level_citations_over_nested_result | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_item_without_citations_falls_back_to_direct_text | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_items_without_explicit_score_default_to_half | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_mixed_valid_and_empty_items | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_multiple_items_merged | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_multiple_items_same_score_stable | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_non_dict_items_skipped | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_realistic_memory_items_from_add_short_term_shape | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_returns_str | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_score_edge_values_handled | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_single_item_with_citations_from_sample | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compress_short_term.py | test_truncation_when_fallback_output_exceeds_limit | MemoryManager | compress_short_term | 1.8 | active |
| test/unit/test_memory_compute_similarity.py | test_all_chunks_empty_body_returns_zero_score | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_chunk_falls_back_to_text_field | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_empty_chunks | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_empty_query_string_handled | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_mixed_valid_and_empty_chunks | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_returns_tuple_of_two | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_score_bounded_between_zero_and_one | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_single_chunk_with_text_snippet | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_compute_similarity.py | test_uses_real_citation_data_from_knowledge_hub | MemoryManager | compute_memory_similarity | 1.4 | active |
| test/unit/test_memory_condition_fn.py | test_threshold | MemoryManager | condition_fn | 1.9 | active |
| test/unit/test_memory_delete_short_term.py | test_delete_all_items | MemoryManager | delete_short_term | 1.10 | active |
| test/unit/test_memory_delete_short_term.py | test_delete_empty_list_noop | MemoryManager | delete_short_term | 1.10 | active |
| test/unit/test_memory_delete_short_term.py | test_delete_non_existent_safe | MemoryManager | delete_short_term | 1.10 | active |
| test/unit/test_memory_delete_short_term.py | test_delete_uses_equality_not_identity | MemoryManager | delete_short_term | 1.10 | active |
| test/unit/test_memory_delete_short_term.py | test_delete_with_realistic_citation_items | MemoryManager | delete_short_term | 1.10 | active |
| test/unit/test_memory_delete_short_term.py | test_removes | MemoryManager | delete_short_term | 1.10 | active |
| test/unit/test_memory_evidence_body.py | test_empty_returns_empty | MemoryManager | _evidence_body | 1.2 | active |
| test/unit/test_memory_evidence_body.py | test_fallback_text | MemoryManager | _evidence_body | 1.2 | active |
| test/unit/test_memory_evidence_body.py | test_text_snippet_preferred | MemoryManager | _evidence_body | 1.2 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_all_citations_empty_returns_empty_list | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_citation_fallback_to_text | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_citations_preferred_over_top_level_text | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_empty_citations_falls_back_to_text | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_empty_result | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_multiple_citations | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_skip_empty_body | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_evidence_chunks_from_result.py | test_top_level_text_when_no_citations | MemoryManager | _evidence_chunks_from_result | 1.3 | active |
| test/unit/test_memory_get_relevant.py | test_top_k | MemoryManager | get_relevant | 1.12 | active |
| test/unit/test_memory_manager_init.py | test_all_memory_layers_initialized | MemoryManager | __init__ | 1.1 | active |
| test/unit/test_memory_manager_init.py | test_episodic_empty | MemoryManager | __init__ | 1.1 | active |
| test/unit/test_memory_manager_init.py | test_long_term_empty | MemoryManager | __init__ | 1.1 | active |
| test/unit/test_memory_manager_init.py | test_memory_layers_are_independent | MemoryManager | __init__ | 1.1 | active |
| test/unit/test_memory_manager_init.py | test_multiple_instances_independent | MemoryManager | __init__ | 1.1 | active |
| test/unit/test_memory_manager_init.py | test_short_term_empty | MemoryManager | __init__ | 1.1 | active |
| test/unit/test_memory_promote_to_long_term.py | test_promote | MemoryManager | promote_to_long_term | 1.11 | active |
| test/unit/test_memory_query_relevant_events.py | test_session_filter | MemoryManager | query_relevant_events | 1.15 | active |
| test/unit/test_memory_retrieve_context.py | test_returns_str | MemoryManager | retrieve_context | 1.13 | active |
| test/unit/test_memory_update_access_count.py | test_increments | MemoryManager | update_access_count | 1.6 | active |
| test/unit/test_orchestrator_answer.py | test_returns_dict | RagOrchestrator | answer |  | active |
| test/unit/test_orchestrator_build_final_evidence_bundle.py | test_sorted_by_task_id | RagOrchestrator | _build_final_evidence_bundle |  | active |
| test/unit/test_orchestrator_build_tool_index_text.py | test_lists_all_tools | RagOrchestrator | build_tool_index_text |  | active |
| test/unit/test_orchestrator_check_global_answer_readiness.py | test_five_keys | RagOrchestrator | _check_global_answer_readiness |  | active |
| test/unit/test_orchestrator_ensure_tools_cache.py | test_idempotent | RagOrchestrator | _ensure_tools_cache |  | active |
| test/unit/test_orchestrator_get_input_schema.py | test_from_cache | RagOrchestrator | get_input_schema |  | active |
| test/unit/test_orchestrator_init.py | test_constructs | RagOrchestrator | __init__ |  | active |
| test/unit/test_orchestrator_merge_subtask_images.py | test_dedupe_by_data | RagOrchestrator | _merge_subtask_images |  | active |
| test/unit/test_orchestrator_should_attach_images.py | test_no_images_false | RagOrchestrator | _should_attach_images |  | active |
| test/unit/test_orchestrator_synthesize_final_answer.py | test_returns_str | RagOrchestrator | _synthesize_final_answer |  | active |
| test/unit/test_planner_init.py | test_constructs | PlannerAgent | __init__ | 4.1 | active |
| test/unit/test_planner_load_routing_hint.py | test_cache_second_call | PlannerAgent | load_routing_hint | replan-planner-load_routing_hint | active |
| test/unit/test_planner_plan.py | test_parses_json_array | PlannerAgent | plan | 4.3 | active |
| test/unit/test_planner_plan.py | test_plan_llm_with_markdown_fence | PlannerAgent | plan | 4.3 | active |
| test/unit/test_planner_replan.py | test_includes_observation | PlannerAgent | replan | 4.4 | active |
