"""TEST_CHANGELOG 追加与 diff 摘要。"""
from pathlib import Path

from harness.test_changelog import append_test_change, format_change_entry, read_changelog


def test_append_test_change_writes_entry(tmp_path: Path):
    path = tmp_path / "test" / "TEST_CHANGELOG.md"
    task = {
        "id": "1.1",
        "target_class": "MemoryManager",
        "symbol": "__init__",
    }
    old = 'def test_old():\n    pytest.skip("implement")\n'
    new = "def test_short_term_empty():\n    assert True\n"
    msg = append_test_change(
        path,
        task,
        test_rel="test/unit/test_memory_manager_init.py",
        action="supplement",
        reason="去掉 skip，补 assert",
        old_code=old,
        new_code=new,
        diff_max_chars=4000,
    )
    assert "已写入" in msg
    text = path.read_text(encoding="utf-8")
    assert "test_memory_manager_init.py" in text
    assert "supplement" in text
    assert "```diff" in text
    assert "test_short_term_empty" in text


def test_append_skips_identical_content(tmp_path: Path):
    path = tmp_path / "TEST_CHANGELOG.md"
    path.write_text(read_changelog(path), encoding="utf-8")
    code = "def test_x():\n    assert 1\n"
    msg = append_test_change(
        path,
        {"id": "x"},
        test_rel="test/unit/test_x.py",
        action="fix",
        reason="noop",
        old_code=code,
        new_code=code,
    )
    assert "未追加" in msg
    assert path.read_text(encoding="utf-8").count("### ") == 0


def test_format_change_entry_gate_flag():
    entry = format_change_entry(
        {"id": "gate.7", "target_class": "Generator", "symbol": "run_subtask", "task_kind": "gate"},
        test_rel="test/unit/test_generator_run_subtask.py",
        action="fix",
        reason="去 skip",
        old_code="def test_a(): pass\n",
        new_code="def test_b(): assert True\n",
        diff_max_chars=2000,
    )
    assert "gate.7" in entry
    assert "门禁任务 | 是" in entry
