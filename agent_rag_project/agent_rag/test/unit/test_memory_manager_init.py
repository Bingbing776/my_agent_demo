import pytest

from test.helpers.imports import import_class

MemoryManager = import_class("MemoryManager")

pytestmark = [pytest.mark.unit]


def test_short_term_empty(memory_manager):
    """short_term should be an empty list after init."""
    assert memory_manager.short_term == []
    assert isinstance(memory_manager.short_term, list)


def test_long_term_empty(memory_manager):
    """long_term_collection should be None when not provided."""
    assert memory_manager.long_term_collection is None


def test_episodic_empty(memory_manager):
    """sqlite_conn and qdrant_collection should be None when not provided."""
    assert memory_manager.sqlite_conn is None
    assert memory_manager.qdrant_collection is None


def test_all_memory_layers_initialized(memory_manager):
    """All memory layers, config params, and auxiliary attrs exist after init."""
    # memory layers
    assert hasattr(memory_manager, 'short_term')
    assert hasattr(memory_manager, 'long_term_collection')
    assert hasattr(memory_manager, 'sqlite_conn')
    assert hasattr(memory_manager, 'qdrant_collection')

    # config parameters (corrected attribute names per product code)
    assert hasattr(memory_manager, 'short_term_capacity')
    assert hasattr(memory_manager, 'threshold')
    assert hasattr(memory_manager, 'compress_truncate_n')
    assert hasattr(memory_manager, 'w_time')
    assert hasattr(memory_manager, 'w_importance')
    assert hasattr(memory_manager, 'w_freq')
    assert hasattr(memory_manager, 'short_term_k')
    assert hasattr(memory_manager, 'long_term_k')
    assert hasattr(memory_manager, 'episodic_k')

    # auxiliary attributes (timestamp/access_count are per-item, not global)
    assert hasattr(memory_manager, '_llm')
    assert hasattr(memory_manager, '_encoder')

    # type checks
    assert isinstance(memory_manager.short_term_capacity, int)
    assert isinstance(memory_manager.threshold, float)
    assert isinstance(memory_manager.compress_truncate_n, int)
    assert isinstance(memory_manager.w_time, float)
    assert isinstance(memory_manager.w_importance, float)
    assert isinstance(memory_manager.w_freq, float)
    assert isinstance(memory_manager.short_term_k, int)
    assert isinstance(memory_manager.long_term_k, int)
    assert isinstance(memory_manager.episodic_k, int)

    # default values with no config
    bare = MemoryManager()
    assert bare.short_term_capacity == 50
    assert bare.threshold == 0.7
    assert bare.compress_truncate_n == 512
    assert bare.w_time == 0.3
    assert bare.w_importance == 0.5
    assert bare.w_freq == 0.2
    assert bare.short_term_k == 5
    assert bare.long_term_k == 3
    assert bare.episodic_k == 2


def test_memory_layers_are_independent():
    """short_term and external storage instances should be independent objects."""
    mock_collection = object()
    mock_sqlite = object()
    mock_qdrant = object()
    mgr = MemoryManager(
        long_term_collection=mock_collection,
        sqlite_conn=mock_sqlite,
        qdrant_collection=mock_qdrant,
    )
    # short_term is independent from external objects
    assert mgr.short_term is not mock_collection
    assert mgr.short_term is not mock_sqlite
    assert mgr.short_term is not mock_qdrant
    # external objects are distinct
    assert mgr.long_term_collection is not mgr.sqlite_conn
    assert mgr.long_term_collection is not mgr.qdrant_collection
    assert mgr.sqlite_conn is not mgr.qdrant_collection


def test_multiple_instances_independent(memory_manager):
    """Multiple MemoryManager instances have independent short_term."""
    manager2 = MemoryManager()
    memory_manager.short_term.append({"key": "test"})
    assert memory_manager.short_term == [{"key": "test"}]
    assert manager2.short_term == []
    assert memory_manager.short_term is not manager2.short_term
