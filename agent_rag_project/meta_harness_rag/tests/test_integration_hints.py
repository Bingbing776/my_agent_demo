"""MODULAR 集成 hint 匹配与注入。"""
from __future__ import annotations

from harness.integration_hints import (
    collect_integration_hints,
    matched_hint_specs,
    needs_integration_hints,
    related_symbols_from_issues,
)
from harness.generator.encoder_hints import (
    encoder_implementation_hint,
    needs_encoder_hint,
)


def test_needs_encoder_hint_by_symbol():
    assert needs_encoder_hint(symbol="compute_memory_similarity", issues="")
    assert not needs_encoder_hint(symbol="add_long_term", issues="")


def test_needs_integration_hints_mcp():
    assert needs_integration_hints(
        symbol="call_tool",
        issues="",
        target_file="../agent_rag/agent_rag/mcp/client.py",
    )


def test_needs_integration_hints_executor():
    assert needs_integration_hints(
        symbol="fill_arguments",
        issues="",
        target_file="agent_rag/mcp/executor.py",
    )


def test_needs_integration_hints_by_issues():
    assert needs_integration_hints(
        symbol="other",
        issues="TypeError: DenseEncoder.__init__() missing 1 required positional argument: 'embedding'",
    )
    assert needs_integration_hints(
        symbol="fix",
        issues="LLMFactory.create() got an unexpected keyword argument",
    )


def test_related_symbols_from_issues():
    issues = (
        "File memory_manager.py\n"
        "    self._get_encoder()\n"
        "TypeError in _cosine_similarity"
    )
    related = related_symbols_from_issues(issues, "compute_memory_similarity")
    assert "_get_encoder" in related
    assert "_cosine_similarity" in related


def test_collect_integration_hints_encoder_and_evidence():
    text = collect_integration_hints(
        symbol="compute_memory_similarity",
        issues="self._get_encoder()",
        target_file="agent_rag/memory/memory_manager.py",
    )
    assert "DenseEncoder" in text
    assert "_get_encoder" in text
    assert "_evidence" in text or "证据" in text


def test_collect_integration_hints_mcp():
    text = collect_integration_hints(
        symbol="call_tool",
        issues="",
        target_file="agent_rag/mcp/client.py",
    )
    assert "McpClient" in text
    assert "isError" in text


def test_matched_hint_ids_import_on_bad_import():
    specs = matched_hint_specs(
        symbol="compute_memory_similarity",
        issues="ModuleNotFoundError: No module named 'src'",
        target_file="agent_rag/memory/memory_manager.py",
    )
    ids = {s.hint_id for s in specs}
    assert "import_rules" in ids
    assert "encoder" in ids


def test_encoder_implementation_hint_contains_adapter():
    text = encoder_implementation_hint(
        primary_symbol="compute_memory_similarity",
        related=["_get_encoder"],
    )
    assert "DenseEncoder(embedding=emb)" in text
    assert "_TextEncoderAdapter" in text
    assert "_get_encoder" in text
