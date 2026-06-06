"""Planner replan 回填 target_file 行为。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness.planner.runtime import (
    PlannerRuntime,
    backfill_fix_task,
    parse_observation_task_hints,
)
from harness.types import HarnessTask


def _failed_task() -> HarnessTask:
    return HarnessTask(
        id="1.3",
        module="MemoryManager",
        section="1",
        symbol="_evidence_chunks_from_result",
        title="MemoryManager._evidence_chunks_from_result",
        target_file="../agent_rag/agent_rag/memory/memory_manager.py",
        test_file="test/unit/test_memory_evidence_chunks_from_result.py",
        done_criteria="pytest 通过",
        dependencies=[],
    )


def test_parse_observation_task_hints():
    obs = (
        "子任务: id=1.3 symbol=_evidence_chunks_from_result "
        "target_file=../agent_rag/agent_rag/memory/memory_manager.py test_file=None"
    )
    hints = parse_observation_task_hints(obs)
    assert hints["id"] == "1.3"
    assert hints["symbol"] == "_evidence_chunks_from_result"
    assert hints["target_file"] == "../agent_rag/agent_rag/memory/memory_manager.py"
    assert "test_file" not in hints


def test_backfill_fix_task_from_failed_task():
    fix = HarnessTask(
        id="replan-60",
        module="(replan)",
        symbol="fix",
        target_file="",
    )
    out = backfill_fix_task(fix, failed_task=_failed_task())
    assert out["target_file"] == "../agent_rag/agent_rag/memory/memory_manager.py"
    assert out["symbol"] == "_evidence_chunks_from_result"
    assert out["test_file"] == "test/unit/test_memory_evidence_chunks_from_result.py"
    assert out["module"] == "MemoryManager"


def test_backfill_fix_task_from_observation_when_no_failed_task():
    fix = HarnessTask(id="replan-60", symbol="fix", target_file="")
    obs = (
        "子任务: id=1.3 symbol=_evidence_chunks_from_result "
        "target_file=../agent_rag/agent_rag/memory/memory_manager.py test_file=None"
    )
    out = backfill_fix_task(fix, observation=obs)
    assert out["target_file"] == "../agent_rag/agent_rag/memory/memory_manager.py"
    assert out["symbol"] == "_evidence_chunks_from_result"


def test_node_llm_replan_backfills_empty_target_file():
    rt = PlannerRuntime(
        Path("docs/tech_doc.md"),
        config={},
        package_root=Path("."),
        harness_cfg={"llm_enabled": True, "planner": {"replan_use_llm": True}},
        llm=SimpleNamespace(),
    )

    def fake_chat(_bundle, *, system, user, harness_cfg, agent_key):
        assert "target_file=../agent_rag/agent_rag/memory/memory_manager.py" in user
        return '[{"id":"replan-60","symbol":"fix","target_file":""}]'

    state = {
        "observation": "具体问题:\nmax_inner_steps",
        "failed_task": _failed_task(),
    }
    with patch("harness.planner.runtime.chat", side_effect=fake_chat):
        fixes = rt.node_llm_replan(state)["fix_tasks"]

    assert len(fixes) == 1
    assert fixes[0]["target_file"] == "../agent_rag/agent_rag/memory/memory_manager.py"
    assert fixes[0]["symbol"] == "_evidence_chunks_from_result"


def test_node_fallback_replan_inherits_failed_task():
    rt = PlannerRuntime(
        Path("docs/tech_doc.md"),
        config={},
        package_root=Path("."),
        harness_cfg={"llm_enabled": True},
        llm=SimpleNamespace(),
    )
    rt._index = 60
    state = {"observation": "failed", "fix_tasks": [], "failed_task": _failed_task()}
    fixes = rt.node_fallback_replan(state)["fix_tasks"]
    assert fixes[0]["id"] == "replan-1.3"
    assert fixes[0]["target_file"] == "../agent_rag/agent_rag/memory/memory_manager.py"
