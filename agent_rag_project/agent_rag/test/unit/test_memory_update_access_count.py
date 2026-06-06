import pytest

pytestmark = [pytest.mark.unit]


def test_increments(memory_manager):
    """Test update_access_count: init, increment, cap at 10, non-int, non-dict."""

    # Rule: missing "access_count" key -> initialized to 1
    item_missing = {"query": "q1", "score": 0.5}
    memory_manager.update_access_count(item_missing)
    assert item_missing["access_count"] == 1, (
        "missing access_count should be initialized to 1"
    )

    # Rule: existing key -> increment by 1
    item_zero = {"access_count": 0}
    memory_manager.update_access_count(item_zero)
    assert item_zero["access_count"] == 1

    item_one = {"access_count": 1}
    memory_manager.update_access_count(item_one)
    assert item_one["access_count"] == 2

    item_five = {"access_count": 5}
    memory_manager.update_access_count(item_five)
    assert item_five["access_count"] == 6

    # Rule: cap at 10
    item_nine = {"access_count": 9}
    memory_manager.update_access_count(item_nine)
    assert item_nine["access_count"] == 10, "9 should increment to 10"

    item_ten = {"access_count": 10}
    memory_manager.update_access_count(item_ten)
    assert item_ten["access_count"] == 10, "10 should stay at 10 (cap)"

    item_fifteen = {"access_count": 15}
    memory_manager.update_access_count(item_fifteen)
    assert item_fifteen["access_count"] == 10, "15 should be capped to 10"

    # Rule: non-int access_count -> reset to 1
    item_str = {"access_count": "hello"}
    memory_manager.update_access_count(item_str)
    assert item_str["access_count"] == 1, "non-int string should reset to 1"

    item_none = {"access_count": None}
    memory_manager.update_access_count(item_none)
    assert item_none["access_count"] == 1, "None access_count should reset to 1"

    # Rule: non-dict input -> no mutation, returns None
    non_dict = [1, 2, 3]
    result = memory_manager.update_access_count(non_dict)
    assert result is None, "non-dict input should return None"
    assert non_dict == [1, 2, 3], "non-dict input should not be mutated"

    # Rule: return value is always None for dict inputs too
    item = {"access_count": 0}
    ret = memory_manager.update_access_count(item)
    assert ret is None, "should return None for dict input as well"
