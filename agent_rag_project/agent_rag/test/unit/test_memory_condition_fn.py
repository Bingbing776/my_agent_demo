"""Stage 5.7 \u2014 MemoryManager.condition_fn. See docs/test_outline.md"""
import pytest
from datetime import datetime, timedelta
from math import exp

pytestmark = [pytest.mark.unit]


def test_threshold(memory_manager):
    """Test condition_fn determines promotion eligibility based on weighted score.

    The method computes: total = w_time * score_time + w_importance * score_importance
    + w_freq * score_freq, and returns True when total >= threshold (default 0.7).
    """
    # -- non-dict inputs: must return False --
    assert memory_manager.condition_fn(None) is False, "None input should return False"
    assert memory_manager.condition_fn([]) is False, "list input should return False"
    assert memory_manager.condition_fn("invalid") is False, "str input should return False"
    assert memory_manager.condition_fn(42) is False, "int input should return False"

    # -- empty dict: all fields default, score=0.0, no timestamp, no access -> False --
    # score_time=0.0 (no timestamp), score_importance=0.0, score_freq=0.0 => total=0.0
    assert memory_manager.condition_fn({}) is False, "empty dict should not promote"

    # -- high-score item with recent timestamp and high access: should promote --
    # score_time ~ 1.0, score_importance=1.0, score_freq=1-exp(-5)~0.9933
    # total ~ 0.3*1.0 + 0.5*1.0 + 0.2*0.9933 = 0.9987 >= 0.7
    high_item = {
        "query": "test query",
        "result": {"text": "test result"},
        "session_id": "s1",
        "timestamp": datetime.now(),
        "score": 1.0,
        "access_count": 5,
    }
    assert memory_manager.condition_fn(high_item) is True, (
        "item with score=1.0, recent timestamp, access_count=5 should promote"
    )

    # -- low-score item with no timestamp and no access: should not promote --
    # score_time=0.0, score_importance=0.0, score_freq=0.0 => total=0.0 < 0.7
    low_item = {
        "query": "test query",
        "result": {"text": "test result"},
        "timestamp": None,
        "score": 0.0,
        "access_count": 0,
    }
    assert memory_manager.condition_fn(low_item) is False, (
        "item with score=0.0, no timestamp, access_count=0 should not promote"
    )

    # -- old timestamp: time fully decayed, pulls total below threshold --
    # score_time = max(0, 1 - 48/24) = 0.0
    # score_importance = 0.5, score_freq = 0.0
    # total = 0.3*0.0 + 0.5*0.5 + 0.2*0.0 = 0.25 < 0.7
    old_item = {
        "query": "test",
        "timestamp": datetime.now() - timedelta(hours=48),
        "score": 0.5,
        "access_count": 0,
    }
    assert memory_manager.condition_fn(old_item) is False, (
        "48h-old timestamp + score=0.5 + access_count=0 should not promote"
    )

    # -- moderate score + recent + some access: borderline above threshold --
    # score_time ~ 1.0, score_importance=0.7, access_count=2
    # score_freq = 1 - exp(-2) ~ 0.8647
    # total = 0.3*1.0 + 0.5*0.7 + 0.2*0.8647 ~ 0.8229 >= 0.7
    promote_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": 0.7,
        "access_count": 2,
    }
    assert memory_manager.condition_fn(promote_item) is True, (
        "score=0.7 + recent + access_count=2 should promote (total ~0.82)"
    )

    # -- borderline at exactly threshold --
    # score_time ~ 1.0, score_importance=0.8, access_count=0
    # total = 0.3*1.0 + 0.5*0.8 + 0.2*0.0 = 0.7 >= 0.7
    exact_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": 0.8,
        "access_count": 0,
    }
    assert memory_manager.condition_fn(exact_item) is True, (
        "score=0.8 + recent + access_count=0 should promote (total exactly 0.7)"
    )

    # -- just below threshold --
    # score_time ~ 1.0, score_importance=0.6, access_count=0
    # total = 0.3*1.0 + 0.5*0.6 = 0.6 < 0.7
    below_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": 0.6,
        "access_count": 0,
    }
    assert memory_manager.condition_fn(below_item) is False, (
        "score=0.6 + recent + access_count=0 should not promote (total 0.6 < 0.7)"
    )

    # -- missing score field: defaults to 0.0 --
    # score_time ~ 1.0, score_importance=0.0, access_count=0
    # total = 0.3*1.0 + 0.5*0.0 + 0.2*0.0 = 0.3 < 0.7
    no_score_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "access_count": 0,
    }
    assert memory_manager.condition_fn(no_score_item) is False, (
        "missing score defaults to 0.0, should not promote"
    )

    # -- missing access_count: defaults to 0 --
    # score_time ~ 1.0, score_importance=0.9, score_freq=0.0
    # total = 0.3*1.0 + 0.5*0.9 = 0.75 >= 0.7
    no_access_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": 0.9,
    }
    assert memory_manager.condition_fn(no_access_item) is True, (
        "score=0.9 + recent + default access_count should promote (total 0.75)"
    )

    # -- score > 1.0: clamped to 1.0 --
    # score_time ~ 1.0, score_importance=1.0 (clamped), access_count=0
    # total = 0.3*1.0 + 0.5*1.0 = 0.8 >= 0.7
    over_score_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": 2.5,
        "access_count": 0,
    }
    assert memory_manager.condition_fn(over_score_item) is True, (
        "score=2.5 clamped to 1.0 + recent should promote (total 0.8)"
    )

    # -- negative score: clamped to 0.0 --
    # score_time ~ 1.0, score_importance=0.0 (clamped), access_count=0
    # total = 0.3*1.0 = 0.3 < 0.7
    neg_score_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": -0.5,
        "access_count": 0,
    }
    assert memory_manager.condition_fn(neg_score_item) is False, (
        "negative score clamped to 0.0 should not promote"
    )

    # -- high access count can compensate for low score --
    # score_time ~ 1.0, score_importance=0.41, access_count=10
    # score_freq = 1 - exp(-10) ~ 0.99995
    # total = 0.3*1.0 + 0.5*0.41 + 0.2*0.99995 = 0.3 + 0.205 + 0.19999 = 0.70499 >= 0.7
    freq_comp_item = {
        "query": "test",
        "timestamp": datetime.now(),
        "score": 0.41,
        "access_count": 10,
    }
    assert memory_manager.condition_fn(freq_comp_item) is True, (
        "score=0.41 + access_count=10 should promote via frequency compensation (total ~0.705)"
    )

    # -- verify return type is always bool --
    assert isinstance(memory_manager.condition_fn(high_item), bool)
    assert isinstance(memory_manager.condition_fn({}), bool)
    assert isinstance(memory_manager.condition_fn(None), bool)
