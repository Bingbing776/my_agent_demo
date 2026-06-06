"""Tests for Evaluator coverage FC cache within a subtask inner loop."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.evaluator.runtime import EvaluatorRuntime


def _runtime(tmp_path: Path) -> EvaluatorRuntime:
    product = tmp_path / "agent_rag"
    test_dir = product / "test" / "unit"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_memory_evidence_body.py"
    test_file.write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    cfg = {
        "write_tests": True,
        "use_llm": False,
        "use_function_calling": False,
        "skip_coverage_recheck_when_stable": True,
    }
    harness_cfg = {"product_root": str(product), "llm_enabled": False}
    rt = EvaluatorRuntime(
        cfg,
        package_root=tmp_path,
        harness_cfg=harness_cfg,
        llm=object(),  # type: ignore[arg-type]
    )
    return rt


def test_coverage_cache_hit_on_second_assess(tmp_path):
    rt = _runtime(tmp_path)
    task = {
        "id": "1.2",
        "target_class": "MemoryManager",
        "symbol": "_evidence_body",
        "test_file": "test/unit/test_memory_evidence_body.py",
    }
    calls = {"n": 0}

    def fake_decide(task, draft, *, gate=False):
        calls["n"] += 1
        return "skip", "tests complete"

    rt.decide_test_action = fake_decide  # type: ignore[method-assign]

    out1 = rt.node_assess_and_ensure_tests({"task": dict(task), "draft_text": ""})
    out2 = rt.node_assess_and_ensure_tests({"task": dict(task), "draft_text": ""})

    assert calls["n"] == 1
    assert out1["test_action"] == "skip"
    assert out2["test_action"] == "skip"
    assert "coverage 缓存" not in out1["test_note"]
    assert "coverage 缓存" in out2["test_note"]


def test_coverage_cache_miss_after_test_file_changes(tmp_path):
    rt = _runtime(tmp_path)
    task = {
        "id": "1.2",
        "test_file": "test/unit/test_memory_evidence_body.py",
    }
    rt._store_coverage_cache(task, "skip", "tests complete")

    test_path = rt.product_root / "test/unit/test_memory_evidence_body.py"
    test_path.write_text("def test_new():\n    assert 1\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_decide(task, draft, *, gate=False):
        calls["n"] += 1
        return "skip", "fresh fc"

    rt.decide_test_action = fake_decide  # type: ignore[method-assign]

    out = rt.node_assess_and_ensure_tests({"task": dict(task), "draft_text": ""})

    assert calls["n"] == 1
    assert out["test_reason"] == "fresh fc"
    assert "coverage 缓存" not in out["test_note"]


def test_coverage_cache_cleared_on_non_skip_action(tmp_path):
    rt = _runtime(tmp_path)
    task = {"id": "1.2", "test_file": "test/unit/test_memory_evidence_body.py"}
    rt._store_coverage_cache(task, "skip", "old")

    rt._store_coverage_cache(task, "create", "need new tests")
    assert rt._get_cached_coverage(task) is None


def test_invalidate_context_cache_clears_coverage(tmp_path):
    rt = _runtime(tmp_path)
    task = {"id": "1.2", "test_file": "test/unit/test_memory_evidence_body.py"}
    rt._store_coverage_cache(task, "skip", "cached")
    rt.invalidate_context_cache()
    assert rt._get_cached_coverage(task) is None
