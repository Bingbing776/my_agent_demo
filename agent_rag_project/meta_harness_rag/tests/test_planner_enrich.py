"""Planner node_enrich_tasks 分批 enrich 行为。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness.planner.runtime import PlannerRuntime
from harness.types import HarnessTask


def _runtime(*, batch_size: int = 2, task_limit: int | None = None) -> PlannerRuntime:
    harness_cfg = {
        "llm_enabled": True,
        "planner": {
            "enrich_descriptions": True,
            "enrich_batch_size": batch_size,
        },
    }
    if task_limit is not None:
        harness_cfg["planner"]["enrich_task_limit"] = task_limit
    rt = PlannerRuntime(
        Path("docs/tech_doc.md"),
        config={},
        package_root=Path("."),
        harness_cfg=harness_cfg,
        llm=SimpleNamespace(),  # truthy stub; chat is patched
    )
    return rt


def _unit_task(n: int) -> HarnessTask:
    return HarnessTask(
        id=f"1.{n}",
        symbol=f"fn{n}",
        target_file=f"../agent_rag/f{n}.py",
        description=f"template {n}",
        done_criteria=f"criteria {n}",
        dependencies=[],
    )


def test_enrich_tasks_batches_all_unit_tasks():
    rt = _runtime(batch_size=2)
    tasks = [_unit_task(1), _unit_task(2), _unit_task(3)]
    calls: list[str] = []

    def fake_chat(_bundle, *, system, user, harness_cfg, agent_key):
        calls.append(user)
        if "第 1/2 批" in user:
            return '[{"id":"1.1","description":"d1","done_criteria":"c1"},{"id":"1.2","description":"d2","done_criteria":"c2"}]'
        return '[{"id":"1.3","description":"d3","done_criteria":"c3"}]'

    with patch("harness.planner.runtime.chat", side_effect=fake_chat):
        out = rt.node_enrich_tasks({"tasks": tasks, "doc_text": "# doc"})["tasks"]

    assert len(calls) == 2
    assert out[0]["description"] == "d1"
    assert out[2]["done_criteria"] == "c3"


def test_enrich_task_limit_caps_total():
    rt = _runtime(batch_size=10, task_limit=2)
    tasks = [_unit_task(1), _unit_task(2), _unit_task(3)]

    def fake_chat(_bundle, *, system, user, harness_cfg, agent_key):
        return '[{"id":"1.1","description":"d1","done_criteria":"c1"},{"id":"1.2","description":"d2","done_criteria":"c2"}]'

    with patch("harness.planner.runtime.chat", side_effect=fake_chat) as mock_chat:
        out = rt.node_enrich_tasks({"tasks": tasks, "doc_text": "# doc"})["tasks"]

    assert mock_chat.call_count == 1
    assert out[0]["description"] == "d1"
    assert out[2]["description"] == "template 3"
