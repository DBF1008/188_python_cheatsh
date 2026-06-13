"""
Regression tests for ``routing.Router.get_topics_list`` caching.

``get_topics_list`` is called with two different argument sets:

* keyword search uses ``get_topics_list(skip_internal=True, skip_dirs=True)``
  to get a *filtered* list (no internal pages, no ``cheat.sheets`` dirs);
* the HTML input hint datalist, ``/:list``, unknown-topic suggestions and
  ``:random`` use ``get_topics_list()`` and need the *full* list.

These previously shared a single cache slot, so whichever call ran first
won and the other silently lost internal/dir topics. The tests below pin
the per-argument caching by exercising the real ``Router`` methods on a
small, injected adapter set (so they stay deterministic and offline).
"""

from routing import Router
from adapter.internal import InternalPages, UnknownPages


def _make_router():
    """
    Build a ``Router`` with a controlled, deterministic adapter set.

    ``Router.__init__`` constructs every active adapter (git checkouts,
    language detection, ...). We only need the topic-list bookkeeping, so
    we bypass it with ``__new__`` and inject a minimal state: real
    ``InternalPages``/``UnknownPages`` adapters (used by the ``:list`` and
    suggestion scenarios) plus dummy sources whose names alone drive
    ``get_topics_list``.
    """

    router = Router.__new__(Router)
    router._cached_topics_list = {}
    router._cached_topic_type = {}

    router._topic_list = {
        "internal": [":list", ":help"],
        "unknown": [],
        "cheat.sheets dir": ["python/"],
        "cheat.sheets": ["python/copy-file", "git/log"],
        "tldr": ["ls", "tar"],
        "fosdem": ["fosdem-2020"],
    }

    router._adapter = {
        "internal": InternalPages(
            get_topic_type=router.get_topic_type,
            get_topics_list=router.get_topics_list,
        ),
        "unknown": UnknownPages(
            get_topic_type=router.get_topic_type,
            get_topics_list=router.get_topics_list,
        ),
        "cheat.sheets dir": object(),
        "cheat.sheets": object(),
        "tldr": object(),
        "fosdem": object(),
    }

    return router


def test_topics_list_filtered_and_full_are_independent():
    router = _make_router()

    # Keyword search asks for the filtered variant first; this is what
    # used to poison the shared cache for everyone else.
    filtered = router.get_topics_list(skip_internal=True, skip_dirs=True)
    assert ":list" not in filtered          # internal pages dropped
    assert ":help" not in filtered
    assert "python/" not in filtered        # cheat.sheets dir dropped
    assert "ls" in filtered                 # ordinary topics kept

    # The full list must still contain internal + dir topics.
    full = router.get_topics_list()
    assert ":list" in full
    assert ":help" in full
    assert "python/" in full
    assert "ls" in full

    # "fosdem" is always skipped, regardless of the arguments.
    assert "fosdem-2020" not in filtered
    assert "fosdem-2020" not in full

    # The full call must not have overwritten the filtered cache entry.
    assert router.get_topics_list(skip_internal=True, skip_dirs=True) == filtered


def test_html_input_hint_datalist_is_full_after_search():
    # Scenario: keyword search, then rendering the HTML input hint.
    # cheat_wrapper builds answer_data["topics_list"] = get_topics_list()
    # and html.py emits one <option> per topic into the <datalist>.
    router = _make_router()
    router.get_topics_list(skip_internal=True, skip_dirs=True)   # search first

    topics_list = router.get_topics_list()                       # datalist source
    options = "\n".join("<option value='%s'></option>" % x for x in topics_list)

    assert "<option value=':list'></option>" in options
    assert "<option value='python/'></option>" in options
    assert "<option value='ls'></option>" in options


def test_internal_list_page_is_full_after_search():
    # Scenario: keyword search, then the ":list" internal page.
    router = _make_router()
    router.get_topics_list(skip_internal=True, skip_dirs=True)   # search first

    page = router._adapter["internal"]._get_page(":list")
    lines = page.strip().split("\n")

    assert ":list" in lines        # internal topic present
    assert ":help" in lines
    assert "python/" in lines      # cheat.sheets dir present
    assert "ls" in lines


def test_unknown_suggestions_include_internal_after_search():
    # Scenario: keyword search, then suggestions for an unknown ":"-topic.
    router = _make_router()
    router.get_topics_list(skip_internal=True, skip_dirs=True)   # search first

    suggestion = router._adapter["unknown"]._get_page(":lst")

    # ":list" is the closest internal topic. Before the fix the polluted
    # cache had no ":"-prefixed topics, so the suggestion list was empty.
    assert ":list" in suggestion
