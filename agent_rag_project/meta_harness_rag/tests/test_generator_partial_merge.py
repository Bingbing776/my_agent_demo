"""Tests for tightened partial merge guards in GeneratorRuntime."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.generator.runtime import GeneratorRuntime
from harness.types import HarnessTask


def _runtime(tmp_path: Path) -> GeneratorRuntime:
    return GeneratorRuntime(
        config={"allow_partial_merge": True, "merge_into_class": True},
        package_root=tmp_path,
        tech_doc_path=tmp_path / "tech_doc.md",
        harness_cfg={"llm_enabled": False},
    )


def test_partial_merge_rejects_helper_only_when_primary_broken(tmp_path: Path):
    product = tmp_path / "agent_rag" / "mcp" / "executor.py"
    product.parent.mkdir(parents=True)
    product.write_text(
        "class Executor:\n"
        "    async def execute_task(self, task, get_input_schema):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    rt = _runtime(tmp_path)
    task: HarnessTask = {
        "id": "3.6",
        "symbol": "execute_task",
        "target_class": "Executor",
        "target_file": "agent_rag/mcp/executor.py",
    }
    broken_primary = '''\
    def _stub_helper(self):
        return None

    async def execute_task(self, task, get_input_schema):
        return {"broken": True
'''
    partial = rt._try_partial_method_merge(product.read_text(encoding="utf-8"), broken_primary, task)
    assert partial is None


def test_partial_merge_accepts_valid_primary(tmp_path: Path):
    product = tmp_path / "agent_rag" / "mcp" / "executor.py"
    product.parent.mkdir(parents=True)
    product.write_text(
        "class Executor:\n"
        "    async def execute_task(self, task, get_input_schema):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    rt = _runtime(tmp_path)
    task: HarnessTask = {
        "id": "3.6",
        "symbol": "execute_task",
        "target_class": "Executor",
        "target_file": "agent_rag/mcp/executor.py",
    }
    new_code = '''\
async def execute_task(self, task, get_input_schema):
    return {"ok": True}
'''
    partial = rt._try_partial_method_merge(product.read_text(encoding="utf-8"), new_code, task)
    assert partial is not None
    assert 'return {"ok": True}' in partial
    assert rt._merge_guard_reason(partial, task, code=new_code) is None
