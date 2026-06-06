import pytest

pytestmark = [pytest.mark.unit]


def test_consecutive_errors_hard_fail(evaluator):
    """quick_rule_check returns hard_fail EvalResult when tool_trace_summary\n    contains N consecutive lines with '[error]' marker (default N=3).\n    Returns None when no hard rule matches, signalling caller to proceed\n    to full LLM evaluate."""

    task = {"description": "retrieve evidence for claim X", "intent": "retrieve"}

    # -- 3 consecutive errors triggers hard_fail (default threshold) --
    trace_3 = "[error] mcp call failed\n[error] retry failed\n[error] final attempt"
    result = evaluator.quick_rule_check(task, trace_3)
    assert result is not None, "3 consecutive [error] lines must trigger hard_fail"
    assert isinstance(result, dict)
    assert set(result.keys()) == {"passed", "score", "require_more_tools", "status", "issues"}, \
        "result must contain exactly the 5 EvalResult keys"
    assert result["passed"] is False
    assert result["score"] == 0.0
    assert result["require_more_tools"] is False
    assert result["status"] == "hard_fail"
    assert isinstance(result["issues"], str)
    assert len(result["issues"]) > 0

    # -- 4+ consecutive errors also triggers --
    trace_4 = "[error] a\n[error] b\n[error] c\n[error] d"
    result4 = evaluator.quick_rule_check(task, trace_4)
    assert result4 is not None, "4 consecutive [error] lines must also trigger hard_fail"
    assert result4["status"] == "hard_fail"
    assert result4["passed"] is False

    # -- 2 consecutive errors: below default threshold, must NOT trigger --
    trace_2 = "[error] fail1\n[error] fail2"
    result2 = evaluator.quick_rule_check(task, trace_2)
    assert result2 is None, "2 consecutive [error] lines must NOT trigger (default threshold=3)"

    # -- Non-consecutive errors must NOT trigger --
    trace_gapped = "[error] fail1\nok step\n[error] fail2\nok step\n[error] fail3"
    result_gapped = evaluator.quick_rule_check(task, trace_gapped)
    assert result_gapped is None, "non-consecutive [error] lines must NOT trigger"

    # -- Single error must NOT trigger --
    trace_single = "[error] only one failure"
    result_single = evaluator.quick_rule_check(task, trace_single)
    assert result_single is None, "single [error] line must NOT trigger"

    # -- Empty trace returns None --
    result_empty = evaluator.quick_rule_check(task, "")
    assert result_empty is None, "empty trace must return None"

    # -- None trace must not crash, returns None --
    result_none = evaluator.quick_rule_check(task, None)
    assert result_none is None, "None trace must return None without crashing"

    # -- Whitespace-only trace returns None --
    result_ws = evaluator.quick_rule_check(task, "   \n  \n   ")
    assert result_ws is None, "whitespace-only trace must return None"

    # -- Case-insensitive [error] matching --
    trace_mixed = "[Error] fail1\n[ERROR] fail2\n[error] fail3"
    result_mixed = evaluator.quick_rule_check(task, trace_mixed)
    assert result_mixed is not None, "[error] matching must be case-insensitive"
    assert result_mixed["status"] == "hard_fail"

    # -- Blank lines between [error] lines are skipped; errors remain consecutive --
    trace_blanks = "[error] a\n\n[error] b\n\n[error] c"
    result_blanks = evaluator.quick_rule_check(task, trace_blanks)
    assert result_blanks is not None, "blank lines must be skipped; 3 [error] lines remain consecutive"

    # -- Custom threshold via flat config key --
    from agent_rag.agents.evaluator import Evaluator
    e_flat = Evaluator({"quick_rule_error_streak": 2, "eval_system_prompt": "test"})
    result_custom = e_flat.quick_rule_check(task, trace_2)
    assert result_custom is not None, "custom threshold=2 must trigger on 2 consecutive errors"
    assert result_custom["status"] == "hard_fail"

    # -- Custom threshold via nested config path --
    e_nested = Evaluator({
        "rag_agent": {"evaluator": {"quick_rule_error_streak": 4}},
        "eval_system_prompt": "test"
    })
    result_nested = e_nested.quick_rule_check(task, trace_3)
    assert result_nested is None, "nested threshold=4 must NOT trigger on 3 consecutive errors"
    result_nested4 = e_nested.quick_rule_check(task, trace_4)
    assert result_nested4 is not None, "nested threshold=4 must trigger on 4 consecutive errors"
    assert result_nested4["status"] == "hard_fail"

    # -- Threshold clamped to minimum 1 via config --
    e_min = Evaluator({"quick_rule_error_streak": 0, "eval_system_prompt": "test"})
    result_min = e_min.quick_rule_check(task, "[error] single")
    assert result_min is not None, "threshold clamped to 1 must trigger on 1 error"
    assert result_min["status"] == "hard_fail"

    # -- Invalid threshold value falls back to default 3 --
    e_invalid = Evaluator({"quick_rule_error_streak": "abc", "eval_system_prompt": "test"})
    result_invalid = e_invalid.quick_rule_check(task, trace_3)
    assert result_invalid is not None, "invalid threshold must fall back to default 3"
    result_invalid2 = e_invalid.quick_rule_check(task, trace_2)
    assert result_invalid2 is None, "invalid threshold fallback=3 must NOT trigger on 2 errors"
