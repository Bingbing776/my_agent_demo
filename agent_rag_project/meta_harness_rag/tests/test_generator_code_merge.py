"""Tests for Generator code merge into target classes."""
from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.generator.code_merge import (
    merge_all_methods_from_draft,
    merge_method_into_class,
    merge_module_header_from_draft,
)


EXISTING = '''\
class MemoryManager:
    def _get_encoder(self):
        return self._encoder

def _evidence_body(self, c: dict) -> str:
        s = (c.get("text_snippet") or "").strip()
        if s:
            return s
        return (c.get("text") or "").strip()
'''

NEW_METHOD = '''\
def _evidence_body(self, c: dict) -> str:
    s = (c.get("text_snippet") or "").strip()
    if s:
        return s
    return (c.get("text") or "").strip()
'''


def test_merge_moves_module_level_method_into_class():
    merged = merge_method_into_class(
        EXISTING,
        NEW_METHOD,
        symbol="_evidence_body",
        target_class="MemoryManager",
    )
    ast.parse(merged)
    assert "class MemoryManager:" in merged
    assert merged.count("def _evidence_body") == 1
    assert "\ndef _evidence_body" not in merged.replace("    def _evidence_body", "")
    assert "    def _evidence_body(self, c: dict)" in merged


def test_merge_replaces_existing_class_method():
    existing = '''\
class MemoryManager:
    def _evidence_body(self, c: dict) -> str:
        return "old"
'''
    new_code = '''\
def _evidence_body(self, c: dict) -> str:
    return "new"
'''
    merged = merge_method_into_class(
        existing,
        new_code,
        symbol="_evidence_body",
        target_class="MemoryManager",
    )
    ast.parse(merged)
    assert 'return "new"' in merged
    assert 'return "old"' not in merged


def test_merge_accepts_indented_snippet_from_llm():
    new_code = '''\
    def _evidence_body(self, c: dict) -> str:
        return (c.get("text") or "").strip()
'''
    merged = merge_method_into_class(
        "class MemoryManager:\n    pass\n",
        new_code,
        symbol="_evidence_body",
        target_class="MemoryManager",
    )
    ast.parse(merged)
    assert "    def _evidence_body(self, c: dict)" in merged


def test_merge_refuses_when_target_class_missing():
    existing = "def unrelated():\n    pass\n"
    new_code = '''\
def execute_task(self, task, get_input_schema):
    return {}
'''
    merged = merge_method_into_class(
        existing,
        new_code,
        symbol="execute_task",
        target_class="Executor",
    )
    assert merged is None


def test_merge_refuses_test_script_instead_of_product_method():
    existing = '''\
class Executor:
    async def call_tool(self, name, arguments):
        return {}
'''
    test_script = '''\
import asyncio

async def test_fill_arguments():
    pass

if __name__ == "__main__":
    asyncio.run(test_fill_arguments())
'''
    merged = merge_method_into_class(
        existing,
        test_script,
        symbol="fill_arguments",
        target_class="Executor",
    )
    assert merged is None


def test_merge_extracts_method_from_class_body_without_whole_file_replace():
    existing = '''\
class Executor:
    def __init__(self, mcp_client, config=None):
        self._mcp = mcp_client
'''
    new_code = '''\
class Executor:
    async def fill_arguments(self, tool_name, input_schema, user_intent, prior_observation):
        return {"query": "ok"}
'''
    merged = merge_method_into_class(
        existing,
        new_code,
        symbol="fill_arguments",
        target_class="Executor",
    )
    ast.parse(merged)
    assert "async def fill_arguments" in merged
    assert "def __init__" in merged
    assert merged.count("class Executor") == 1
    assert "return {\"query\": \"ok\"}" in merged


def test_merge_skips_test_helper_defs_in_multi_merge():
    from harness.generator.code_merge import merge_all_methods_from_draft

    existing = "class Executor:\n    pass\n"
    new_code = '''\
def test_fill_arguments():
    assert True

async def fill_arguments(self, tool_name, input_schema, user_intent, prior_observation):
    return {}
'''
    merged = merge_all_methods_from_draft(
        existing,
        new_code,
        symbols=["test_fill_arguments", "fill_arguments"],
        target_class="Executor",
    )
    ast.parse(merged)
    assert "def test_fill_arguments" not in merged
    assert "async def fill_arguments" in merged


def test_merge_helper_only_without_primary_symbol():
    from harness.generator.code_merge import merge_all_methods_from_draft

    existing = '''\
class Executor:
    async def fill_arguments(self, tool_name, input_schema, user_intent, prior_observation):
        return {}

    def _init_llm(self):
        return None
'''
    new_code = '''\
    def _init_llm(self):
        from src.libs.llm.llm_factory import LLMFactory
        return LLMFactory.create({})
'''
    merged = merge_all_methods_from_draft(
        existing,
        new_code,
        symbols=["_init_llm"],
        target_class="Executor",
    )
    ast.parse(merged)
    assert "LLMFactory.create" in merged
    assert "async def fill_arguments" in merged


def test_merge_infers_typing_optional_from_method_annotation():
    existing = '''\
"""Evaluator module."""

class Evaluator:
    pass
'''
    new_code = '''\
def quick_rule_check(self, task: dict, tool_trace_summary: str) -> Optional[dict]:
    return None
'''
    merged = merge_method_into_class(
        existing,
        new_code,
        symbol="quick_rule_check",
        target_class="Evaluator",
    )
    ast.parse(merged)
    assert "from typing import Optional" in merged
    assert "def quick_rule_check" in merged


def test_merge_adds_module_constant_from_draft_preamble():
    existing = '''\
"""Evaluator module."""

class Evaluator:
    def __init__(self, config=None):
        self._config = config or {}
'''
    new_code = '''\
from typing import Optional

_DEFAULT_EVAL_SYSTEM_PROMPT = "Evaluate the subtask."

class Evaluator:
    def quick_rule_check(self, task: dict, tool_trace_summary: str) -> Optional[dict]:
        return None
'''
    merged = merge_all_methods_from_draft(
        existing,
        new_code,
        symbols=["quick_rule_check"],
        target_class="Evaluator",
    )
    ast.parse(merged)
    assert "_DEFAULT_EVAL_SYSTEM_PROMPT" in merged
    assert "from typing import Optional" in merged

