"""Harness 门禁任务（方案 B）：在实现队列中插入 pytest 验收关卡。"""

from __future__ import annotations



from pathlib import Path

from typing import Any



from harness.types import HarnessTask



GATE_TASK_KIND = "gate"

PYTEST_SCOPE_FILE = "file"

PYTEST_SCOPE_DIRECTORY = "directory"

PYTEST_SCOPE_MARKER = "marker"



# section → 本节 unit 测试（门禁改产品后须一并回归）

SECTION_REGRESSION_GLOBS: dict[str, list[str]] = {

    "1": ["test/unit/test_memory_*.py"],

    "2": ["test/unit/test_context_*.py"],

    "3": ["test/unit/test_mcp_*.py", "test/unit/test_executor_*.py"],

    "4": ["test/unit/test_planner_*.py"],

    "5": ["test/unit/test_evaluator_*.py"],

    "6": ["test/unit/test_generator_*.py"],

}



# section → 默认产品文件（skip_implementation: false 且未配 target_file 时使用）

SECTION_DEFAULT_TARGET_FILE: dict[str, str] = {

    "1": "agent_rag/agent_rag/memory/memory_manager.py",

    "2": "agent_rag/agent_rag/context/context_manager.py",

    "3": "agent_rag/agent_rag/mcp/mcp_client.py",

    "4": "agent_rag/agent_rag/agents/planner.py",

    "5": "agent_rag/agent_rag/agents/evaluator.py",

    "6": "agent_rag/agent_rag/agents/generator.py",

}





def is_gate_task(task: HarnessTask) -> bool:

    if str(task.get("task_kind", "")).lower() == GATE_TASK_KIND:

        return True

    tid = str(task.get("id", "")).strip()

    return tid.startswith("gate.")





def gate_allows_product_fix(task: HarnessTask) -> bool:

    """门禁是否允许 Generator 修改 agent_rag 产品实现（默认 gate 仅验收测试）。"""

    return is_gate_task(task) and not bool(task.get("skip_implementation", True))





def _normalize_globs(defn: dict[str, Any]) -> list[str]:

    raw = defn.get("regression_test_globs")

    if raw is None:

        sec = str(defn.get("section", "")).strip().lstrip("§")

        return list(SECTION_REGRESSION_GLOBS.get(sec, []))

    if isinstance(raw, str):

        return [raw.replace("\\", "/")]

    return [str(g).replace("\\", "/") for g in raw if str(g).strip()]





def _default_target_file(defn: dict[str, Any]) -> str:

    explicit = str(defn.get("target_file") or "").replace("\\", "/").strip()

    if explicit:

        return explicit

    if bool(defn.get("skip_implementation", True)):

        return ""

    sec = str(defn.get("section", "")).strip().lstrip("§")

    return SECTION_DEFAULT_TARGET_FILE.get(sec, "")





def collect_gate_pytest_paths(task: HarnessTask, product_root: Path) -> list[str]:

    """

    门禁 pytest 路径：门禁测试文件 +（允许改产品时）本节 regression_test_globs。

    返回相对 product_root 的路径列表。

    """

    rel = str(task.get("test_file", "")).replace("\\", "/").strip()

    scope = str(task.get("pytest_scope", PYTEST_SCOPE_FILE)).strip().lower()

    paths: list[str] = []



    if rel:

        target = product_root / rel.rstrip("/")

        if scope == PYTEST_SCOPE_DIRECTORY and target.is_dir():

            for p in sorted(target.rglob("test_*.py")):

                paths.append(str(p.relative_to(product_root)).replace("\\", "/"))

        elif scope == PYTEST_SCOPE_MARKER:

            marker = str(task.get("pytest_marker", "") or "").strip()

            base = target if target.is_dir() else target.parent

            needle = f"pytest.mark.{marker}" if marker else ""

            if base.is_dir():

                for p in sorted(base.rglob("test_*.py")):

                    try:

                        text = p.read_text(encoding="utf-8", errors="replace")

                    except OSError:

                        continue

                    if not needle or needle in text:

                        paths.append(str(p.relative_to(product_root)).replace("\\", "/"))

        elif target.is_file():

            paths.append(rel)



    if gate_allows_product_fix(task):

        seen = set(paths)

        for pattern in task.get("regression_test_globs") or []:

            pat = str(pattern).replace("\\", "/")

            for p in sorted(product_root.glob(pat)):

                if not p.is_file() or p.suffix != ".py":

                    continue

                rel_p = str(p.relative_to(product_root)).replace("\\", "/")

                if rel_p not in seen:

                    seen.add(rel_p)

                    paths.append(rel_p)



    return paths





def build_gate_task(defn: dict[str, Any], *, order: int) -> HarnessTask:

    """从 harness.yaml milestones.gates[] 项构造 HarnessTask。"""

    gid = str(defn.get("id", "gate.unknown"))

    pytest_target = str(defn.get("test_file", "")).replace("\\", "/")

    scope = str(defn.get("pytest_scope", PYTEST_SCOPE_FILE)).strip().lower()

    marker = str(defn.get("pytest_marker", "") or "").strip()

    extra = defn.get("pytest_extra_args") or []

    if isinstance(extra, str):

        extra = [extra]



    skip_impl = bool(defn.get("skip_implementation", True))

    target_file = _default_target_file(defn)

    regression_globs = _normalize_globs(defn) if not skip_impl else []



    title = str(defn.get("title") or f"门禁 — {gid}")

    if skip_impl:

        desc = str(

            defn.get("description")

            or f"运行 {pytest_target or 'TEST_INDEX 登记范围'} 验收测试；"

            "仅修测试/fixtures/样本，勿改无关产品实现。"

        )

    else:

        desc = str(

            defn.get("description")

            or (

                f"验收 {pytest_target}；可修改产品 {target_file or '(见 section 默认)'}、"

                "门禁测试与本节 unit 测试；修改产品后须 regression 全过。"

            )

        )

    done = str(

        defn.get("done_criteria")

        or f"pytest {pytest_target or '见 TEST_INDEX 门禁行'} 通过"

    )

    if not skip_impl and regression_globs:

        done = (

            f"{done}；且本节单元测试（{', '.join(regression_globs)}）全部通过"

        )



    return HarnessTask(

        id=gid,

        order=order,

        module=str(defn.get("module") or "(gate)"),

        section=str(defn.get("section") or "gate"),

        symbol=str(defn.get("target_symbol") or defn.get("symbol") or "gate"),

        title=title,

        description=desc,

        dependencies=[],

        target_class=str(defn.get("target_class") or "HarnessGate"),

        target_file=target_file,

        test_file=pytest_target,

        done_criteria=done,

        task_kind=GATE_TASK_KIND,

        pytest_scope=scope,

        pytest_marker=marker,

        pytest_extra_args=list(extra),

        skip_implementation=skip_impl,

        regression_test_globs=regression_globs,

        optional=bool(defn.get("optional", False)),

    )





def _section_num(task: HarnessTask) -> str:

    tid = str(task.get("id", ""))

    if "." in tid:

        return tid.split(".", 1)[0]

    return str(task.get("section", "")).replace("§", "").strip()





def _insertion_index(tasks: list[HarnessTask], spec: dict[str, Any]) -> int:

    """返回 gate 应插入到 tasks 列表的下标（插入后 gate 位于该下标）。"""

    insert = str(spec.get("insert", "end")).strip().lower()

    n = len(tasks)



    if insert == "start":

        return 0



    if insert == "end":

        return n



    if insert == "after_task_id":

        after = str(spec.get("after_task_id", "")).strip()

        for i, t in enumerate(tasks):

            if str(t.get("id", "")) == after:

                return i + 1

        return n



    if insert == "after_section":

        section = str(spec.get("section", "")).strip().lstrip("§")

        last_idx = -1

        for i, t in enumerate(tasks):

            if _section_num(t) == section:

                last_idx = i

        return last_idx + 1 if last_idx >= 0 else n



    return n





def inject_gate_tasks(

    tasks: list[HarnessTask],

    harness_cfg: dict[str, Any],

) -> list[HarnessTask]:

    """

    按 milestones 配置在实现任务队列中插入门禁任务。

    插入位置相对**原始 unit 列表**计算，同一下标多个 gate 按配置顺序排列。

    """

    ms = harness_cfg.get("milestones") or {}

    if not ms.get("enabled", True):

        return tasks



    gate_defs = list(ms.get("gates") or [])

    if not gate_defs:

        return tasks



    from collections import defaultdict



    gates_at: dict[int, list[HarnessTask]] = defaultdict(list)

    base = max((int(t.get("order", 0)) for t in tasks), default=0) + 10_000



    for i, gdef in enumerate(gate_defs):

        idx = _insertion_index(tasks, gdef)

        order = int(gdef.get("order", base + i))

        gates_at[idx].append(build_gate_task(gdef, order=order))



    merged: list[HarnessTask] = []

    for i in range(len(tasks) + 1):

        merged.extend(gates_at.get(i, []))

        if i < len(tasks):

            merged.append(dict(tasks[i]))



    for i, t in enumerate(merged):

        t["order"] = (i + 1) * 10

    return merged





def resolve_pytest_argv(task: HarnessTask, product_root: Any) -> list[str]:

    """构造 pytest 命令参数（不含 python -m pytest 前缀）。"""

    root = Path(product_root)

    if gate_allows_product_fix(task):

        paths = collect_gate_pytest_paths(task, root)

        if paths:

            argv = list(paths)

            argv.extend(list(task.get("pytest_extra_args") or []))

            argv.extend(["-q", "--tb=line"])

            return argv



    rel = str(task.get("test_file", "")).replace("\\", "/").strip()

    if not rel:

        return []



    scope = str(task.get("pytest_scope", PYTEST_SCOPE_FILE)).strip().lower()

    marker = str(task.get("pytest_marker", "") or "").strip()

    extra = list(task.get("pytest_extra_args") or [])



    target = root / rel

    argv: list[str] = []



    if scope == PYTEST_SCOPE_MARKER and marker:

        argv.extend(["-m", marker, rel])

    elif scope == PYTEST_SCOPE_DIRECTORY:

        argv.append(rel if rel.endswith("/") else rel)

    else:

        argv.append(rel)



    argv.extend(extra)

    argv.extend(["-q", "--tb=line"])

    return argv


