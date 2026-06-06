"""Stage 6.4 - ContextManager.get_relevant_context. See docs/test_outline.md
Supplemented with edge-case and fallback tests."""
import pytest
from unittest.mock import MagicMock, ANY

pytestmark = [pytest.mark.unit]

# ----------------------------------------------------------------------
# Existing tests (from TEST_INDEX)
# ----------------------------------------------------------------------

def test_fallback_truncation_respects_length(context_manager, monkeypatch):
    """When the fallback concatenation exceeds truncation_length,
it is hard-truncated to exactly truncation_length characters."""
    cm = context_manager
    cm.truncation_length = 50

    # Fill with an entry long enough to exceed the limit with the Q/A prefix
    cm.update_context("X" * 100, "Y" * 100)

    class FailingLLM:
        def chat(self, messages, **kwargs):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(cm, "_get_llm", lambda: FailingLLM())

    result = cm.get_relevant_context("query irrelevant")
    assert isinstance(result, str)
    assert len(result) == cm.truncation_length
    # The truncated content should start with the pattern of the fallback
    assert result.startswith("Q: X"[: cm.truncation_length])


@pytest.mark.parametrize("top_k", [0, -1])
def test_get_relevant_context_top_k_zero_or_negative_returns_empty(
    context_manager, top_k
):
    """When top_k is 0 or negative, the method returns an empty string
without attempting encoding or LLM compression."""
    cm = context_manager

    # populate some context so that a normal call would return something
    cm.update_context("test query", "test answer")
    original_top_k = getattr(cm, "top_k", None)  # restore later if needed
    cm.top_k = top_k

    result = cm.get_relevant_context("any query")
    assert isinstance(result, str)
    assert result == ""

    if original_top_k is not None:
        cm.top_k = original_top_k


def test_llm_failure_falls_back_to_raw_concat(context_manager, monkeypatch):
    """If the LLM call raises an exception, the method falls back to the
raw concatenated Q/A pairs without compression. The fallback output
must still respect the truncation_length limit and contain 'Q:' markers."""
    cm = context_manager
    # Ensure enough space for the fallback content
    cm.truncation_length = 500

    cm.update_context("Hello", "World")
    cm.update_context("What is RAG?", "Retrieval-Augmented Generation")

    # Replace the LLM instance's chat method so it always fails
    class FailingLLM:
        def chat(self, messages, **kwargs):
            raise RuntimeError("LLM down for maintenance")

    # Monkey-patch _get_llm to return our failing instance
    monkeypatch.setattr(cm, "_get_llm", lambda: FailingLLM())

    result = cm.get_relevant_context("Tell me about RAG")
    assert isinstance(result, str)
    assert len(result) > 0
    # Fallback should contain the raw Q/A markers
    assert "Q:" in result, "Fallback output must contain raw 'Q:' markers"
    assert "A:" in result, "Fallback output must contain raw 'A:' markers"
    # The length must respect truncation_length
    assert len(result) <= cm.truncation_length


def test_no_query_emb_falls_back_to_most_recent(context_manager, monkeypatch):
    """When the query embedding cannot be obtained (e.g., empty query after
strip), the most recent k entries (according to timestamp) are used
directly without similarity reordering."""
    cm = context_manager
    # Force top_k to a small number so we can control the outcome
    cm.top_k = 2

    cm.update_context("old Q", "old A")
    cm.update_context("new Q", "new A")
    cm.update_context("newer Q", "newest A")

    # Force LLM failure so we test the raw concatenation fallback path
    class FailingLLM:
        def chat(self, messages, **kwargs):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(cm, "_get_llm", lambda: FailingLLM())

    # An empty query (after strip) should result in an empty query_emb,
    # triggering the else branch that takes the most recent candidates[:k].
    result = cm.get_relevant_context("   ")
    assert isinstance(result, str)
    assert len(result) > 0
    # Since most recent two entries are "new Q"/"new A" and "newer Q"/"newest A",
    # the fallback concatenation should contain both.
    assert "newest A" in result
    assert "new A" in result


def test_returns_str(context_manager, monkeypatch):
    """get_relevant_context returns a compressed context string;
empty context window returns an empty string."""
    cm = context_manager

    # Empty window returns empty string
    result_empty = cm.get_relevant_context("any query")
    assert isinstance(result_empty, str)
    assert result_empty == ""

    # Populate context window with realistic multi-turn entries
    cm.update_context(
        "What is TOPMOST?",
        "TOPMOST is a topic modeling system toolkit."
    )
    cm.update_context(
        "How does it compare to OCTIS?",
        "TOPMOST covers more scenarios including dynamic and cross-lingual."
    )
    cm.update_context(
        "What about its architecture?",
        "It decouples dataset handler, topic model, trainer, and evaluation."
    )

    # Mock LLM to return a known summary to avoid fragile substring checks
    known_summary = "compressed summary of TOPMOST features and architecture"
    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content=known_summary, model="mock")
    monkeypatch.setattr(cm, "_get_llm", lambda: mock_llm)

    result = cm.get_relevant_context("Tell me about TOPMOST features")
    assert isinstance(result, str)
    assert len(result) > 0
    assert len(result) <= cm.truncation_length
    # Verify the known LLM-compressed summary is returned
    assert result == known_summary, (
        "expected LLM-compressed summary to be returned verbatim"
    )

    # Session filter: non-existent session returns empty string
    result_session = cm.get_relevant_context("query", session_id="no-such-session")
    assert result_session == ""


# ----------------------------------------------------------------------
# Supplement (id=2.4) - additional tests to cover all done_criteria
# ----------------------------------------------------------------------

def test_top_k_selection_respects_cosine_similarity(context_manager, monkeypatch):
    """Verify that top-k entries are taken according to descending cosine similarity,
not by recency or insertion order."""
    cm = context_manager
    cm.top_k = 2
    cm.truncation_length = 1000

    # Custom encoder that returns different, deterministic vectors per text.
    class SelectiveEncoder:
        def encode(self, text: str):
            # give "target" a high dot-product with query vector [1,0,0...]
            if "target" in text:
                return [1.0, 0.0]
            return [0.0, 1.0]
    monkeypatch.setattr(cm, "_encoder", SelectiveEncoder())

    # Force LLM failure to test fallback concatenation path directly
    class FailingLLM:
        def chat(self, messages, **kwargs):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(cm, "_get_llm", lambda: FailingLLM())

    # Insert three entries: the middle one should be the most similar.
    cm.update_context("distractor", "dist_answer")
    cm.update_context("target query", "this is the most relevant answer")
    cm.update_context("other distractor", "other_answer")

    result = cm.get_relevant_context("target query")
    assert isinstance(result, str)
    # The compressed context must include the most relevant answer.
    assert "most relevant answer" in result, (
        "top-k selection must prefer the item with highest cosine similarity"
    )
    # Only two items should contribute (k=2), so the first distractor may or may not appear.
    # It should not contain all three answers.
    assert not ("dist_answer" in result and "other_answer" in result), (
        "only top-k entries should be present"
    )


def test_llm_compression_sends_system_prompt(context_manager, monkeypatch):
    """The LLM chat call must include a system prompt describing historical
dialogue summarisation."""
    cm = context_manager
    cm.top_k = 1
    cm.update_context("question", "answer")

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="compressed summary", model="mock")
    monkeypatch.setattr(cm, "_get_llm", lambda: mock_llm)

    _ = cm.get_relevant_context("query")
    mock_llm.chat.assert_called_once()
    messages = mock_llm.chat.call_args[0][0]  # the list of Message objects
    # Find the system message
    system_content = ""
    for msg in messages:
        if getattr(msg, "role", "") == "system":
            system_content = getattr(msg, "content", "")
    assert "\u538b\u7f29" in system_content or "summar" in system_content.lower(), (
        "system prompt must describe compression/summarisation"
    )


def test_encoder_failure_skips_entry(context_manager, monkeypatch):
    """When an individual context entry cannot be encoded, it is skipped without
breaking the whole pipeline."""
    cm = context_manager
    cm.top_k = 2
    cm.truncation_length = 500

    # Encoder that fails on entry containing "bad"
    class FailableEncoder:
        def encode(self, text):
            if "bad" in text:
                raise ValueError("encoding failed")
            # return constant non-zero vector to allow similarity calculation
            return [0.5, 0.5]
    monkeypatch.setattr(cm, "_encoder", FailableEncoder())

    # Force LLM failure to test fallback concatenation path directly
    class FailingLLM:
        def chat(self, messages, **kwargs):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(cm, "_get_llm", lambda: FailingLLM())

    cm.update_context("good query", "good answer")
    cm.update_context("bad query", "bad answer")
    cm.update_context("another good", "another answer")

    result = cm.get_relevant_context("good query")
    assert isinstance(result, str)
    # The good entries should appear, the bad one should not.
    assert "good answer" in result
    assert "another answer" in result
    assert "bad answer" not in result, "entry with encoding failure must be skipped"


def test_truncation_length_applied_on_successful_compression(context_manager, monkeypatch):
    """Even when LLM compression succeeds, the final string must not exceed
truncation_length."""
    cm = context_manager
    cm.top_k = 1
    cm.truncation_length = 30

    cm.update_context("q", "a")
    # Mock LLM returning a long string
    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="X" * 100, model="mock")
    monkeypatch.setattr(cm, "_get_llm", lambda: mock_llm)

    result = cm.get_relevant_context("query")
    assert len(result) == cm.truncation_length
    assert result == "X" * 30


def test_context_window_n_config_used(context_manager, monkeypatch):
    """The internal call to get_context_window should use the value of
config['context_window_n'] (or max_entries fallback)."""
    cm = context_manager
    # set a custom window size
    cm.config["context_window_n"] = 2
    cm.max_entries = 10  # large default, not to be used

    # populate more than the window size
    for i in range(5):
        cm.update_context(f"q{i}", f"a{i}")

    # get_context_window should be called with n=2
    from unittest.mock import patch
    original = cm.get_context_window
    with patch.object(cm, "get_context_window", wraps=original) as spy:
        cm.get_relevant_context("query")
        # the first positional argument should be 2
        assert spy.call_args[0][0] == 2, "get_context_window must receive n from config"


def test_cosine_similarity_zero_norm(context_manager):
    """_cosine_similarity returns 0.0 when either vector has zero norm."""
    cm = context_manager
    zero_vec = [0.0, 0.0]
    non_zero = [1.0, 2.0]
    assert cm._cosine_similarity(zero_vec, non_zero) == 0.0
    assert cm._cosine_similarity(non_zero, zero_vec) == 0.0
    assert cm._cosine_similarity(zero_vec, zero_vec) == 0.0
