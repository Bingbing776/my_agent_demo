"""Tests for permissive draft code extraction."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.generator.draft_extract import (
    code_covers_symbol,
    draft_has_mergeable_product_defs,
    draft_looks_like_test_script,
    extract_code_from_draft,
    list_def_symbols,
    list_product_def_symbols,
    merged_preserves_target_class,
    method_in_target_class,
    prioritize_symbols,
)


def test_extract_all_fenced_blocks():
    draft = "说明\n```python\ndef a():\n    pass\n```\n更多\n```python\ndef b():\n    return 1\n```"
    code = extract_code_from_draft(draft)
    assert "def a():" in code
    assert "def b():" in code


def test_extract_def_blocks_from_prose():
    draft = (
        "需要先修复 helper。\n"
        "    def _cosine_similarity(self, a, b):\n"
        "        return 1.0\n"
        "\n"
        "    def compute_memory_similarity(self, chunks, query_text):\n"
        "        return 0.0, []\n"
    )
    code = extract_code_from_draft(draft)
    assert "def _cosine_similarity" in code
    assert "def compute_memory_similarity" in code


def test_prioritize_helpers_before_primary():
    syms = prioritize_symbols(
        ["compute_memory_similarity", "_cosine_similarity", "_get_encoder"],
        "compute_memory_similarity",
    )
    assert syms == ["_cosine_similarity", "_get_encoder", "compute_memory_similarity"]


def test_list_def_symbols_order():
    code = "def b():\n    pass\n\ndef a():\n    pass\n"
    assert list_def_symbols(code) == ["b", "a"]


def test_code_covers_symbol_rejects_test_name_substring():
    code = "async def test_fill_arguments():\n    pass\n"
    assert code_covers_symbol(code, "fill_arguments") is False


def test_code_covers_symbol_accepts_exact_method():
    code = "    async def fill_arguments(self):\n        pass\n"
    assert code_covers_symbol(code, "fill_arguments", target_class="Executor") is True


def test_code_covers_symbol_finds_method_inside_class():
    code = '''\
class Executor:
    async def fill_arguments(self):
        return {}
'''
    assert code_covers_symbol(code, "fill_arguments", target_class="Executor") is True


def test_draft_looks_like_test_script():
    code = "async def test_fill_arguments():\n    pass\n"
    assert draft_looks_like_test_script(code, "fill_arguments") is True


def test_draft_detects_mock_session_harness():
    code = '''\
class MockSession:
    async def call_tool(self, name, arguments):
        return {}

async def test_fill_arguments():
    client = McpClient(MockSession())
'''
    assert draft_looks_like_test_script(code, "fill_arguments", target_class="Executor") is True


def test_draft_allows_class_method_with_llm_imports():
    code = '''\
class Executor:
    async def fill_arguments(self, tool_name, input_schema, user_intent, prior_observation):
        from src.libs.llm.base_llm import Message
        return {"query": "x"}
'''
    assert draft_looks_like_test_script(code, "fill_arguments", target_class="Executor") is False


def test_merged_preserves_target_class():
    assert merged_preserves_target_class("class Executor:\n    pass\n", "Executor")
    assert not merged_preserves_target_class("async def test_x():\n    pass\n", "Executor")


def test_method_in_target_class():
    source = '''\
class Executor:
    async def execute_task(self, task, get_input_schema):
        return {}

def execute_task():
    pass
'''
    assert method_in_target_class(source, "Executor", "execute_task") is True
    assert method_in_target_class(source, "Executor", "call_tool") is False
    assert method_in_target_class("def execute_task():\n    pass\n", "Executor", "execute_task") is False


def test_helper_only_draft_is_mergeable_without_primary_symbol():
    code = "    def _init_llm(self):\n        return object()\n"
    assert code_covers_symbol(code, "fill_arguments") is False
    assert draft_has_mergeable_product_defs(code) is True
    assert list_product_def_symbols("def test_x():\n    pass\n") == []


def test_prioritize_does_not_append_missing_primary():
    syms = prioritize_symbols(["_helper"], "fill_arguments")
    assert syms == ["_helper"]
    assert "fill_arguments" not in syms
