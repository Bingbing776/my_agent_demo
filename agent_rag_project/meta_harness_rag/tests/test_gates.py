"""门禁任务注入与 pytest 参数解析。"""
from pathlib import Path

from harness.config_loader import load_harness_config, resolve_product_root
from harness.evaluator.runtime import EvaluatorRuntime
from harness.gates import inject_gate_tasks, is_gate_task, resolve_pytest_argv
from harness.planner.parsing import parse_all_tasks


def test_inject_gate_tasks_at_start_and_end():
    hcfg = load_harness_config()
    doc = Path(__file__).resolve().parents[1] / "docs" / "tech_doc.md"
    unit = parse_all_tasks(doc.read_text(encoding="utf-8"), hcfg)
    merged = inject_gate_tasks(unit, hcfg)
    ids = [t["id"] for t in merged]
    assert ids[0] == "gate.1"
    assert ids[-1] == "gate.e2e"
    assert sum(1 for t in merged if is_gate_task(t)) == 4


def test_resolve_pytest_argv_directory():
    hcfg = load_harness_config()
    root = Path(__file__).resolve().parents[2] / "agent_rag"
    task = {
        "test_file": "test/contracts",
        "pytest_scope": "directory",
    }
    argv = resolve_pytest_argv(task, root)
    assert argv[0] == "test/contracts"
    assert "-q" in argv


def test_collect_gate_write_targets_contracts_dir():
    pkg = Path(__file__).resolve().parents[1]
    hcfg = load_harness_config()
    product_root = resolve_product_root(hcfg, pkg)
    ev = hcfg.get("evaluator") or {}
    rt = EvaluatorRuntime(ev, package_root=pkg, harness_cfg=hcfg)
    task = {
        "id": "gate.1",
        "target_class": "ContractGate",
        "symbol": "all",
        "pytest_scope": "directory",
        "task_kind": "gate",
    }
    rt.apply_index_to_task(task)
    assert task.get("test_file") == "test/contracts"
    targets = rt._collect_gate_write_targets(task)
    assert targets
    assert all(t.startswith("test/contracts/") and t.endswith(".py") for t in targets)


def test_collect_gate_write_targets_single_file():
    pkg = Path(__file__).resolve().parents[1]
    hcfg = load_harness_config()
    ev = hcfg.get("evaluator") or {}
    rt = EvaluatorRuntime(ev, package_root=pkg, harness_cfg=hcfg)
    task = {
        "id": "gate.7",
        "target_class": "Generator",
        "symbol": "run_subtask",
        "pytest_scope": "file",
        "task_kind": "gate",
    }
    rt.apply_index_to_task(task)
    assert task.get("test_file") == "test/unit/test_generator_run_subtask.py"
    targets = rt._collect_gate_write_targets(task)
    assert targets == ["test/unit/test_generator_run_subtask.py"]


def test_planner_tasks_have_no_test_file_until_apply_index():
    pkg = Path(__file__).resolve().parents[1]
    hcfg = load_harness_config()
    doc = pkg / "docs" / "tech_doc.md"
    unit = parse_all_tasks(doc.read_text(encoding="utf-8"), hcfg)
    assert unit
    assert not any(t.get("test_file") for t in unit if not str(t.get("id", "")).startswith("gate."))
    rt = EvaluatorRuntime(hcfg.get("evaluator") or {}, package_root=pkg, harness_cfg=hcfg)
    t0 = dict(unit[0])
    rt.apply_index_to_task(t0)
    assert t0.get("test_file")
