"""阶段 5.4 — Evaluator.to_planner_observation。见 docs/test_outline.md"""
import pytest

from test.helpers.samples import sample_eval_result

pytestmark = [pytest.mark.unit]


def test_includes_status(evaluator):
    obs = evaluator.to_planner_observation(
        sample_eval_result(status="needs_replan", passed=False, issues="缺少来源")
    )
    assert obs
    assert "status=needs_replan" in obs
    assert "passed=False" in obs
    assert "缺少来源" in obs


def test_truncates_long_observation(evaluator):
    long_issue = "x" * 500
    obs = evaluator.to_planner_observation(
        sample_eval_result(status="ok", issues=long_issue),
        max_chars=80,
    )
    assert len(obs) <= 80
    assert obs.endswith("…[truncated]")
