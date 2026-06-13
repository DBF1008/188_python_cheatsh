"""
Regression tests for topics list cache separation.

These tests verify that get_topics_list() with different filtering
parameters (skip_internal, skip_dirs) maintains independent caches
so that filtered and unfiltered calls don't pollute each other.

See bug: topics list cache mixing filtered/unfiltered results.
"""

import sys
import os
import types
import unittest
from unittest.mock import MagicMock

# -----------------------------------------------------------------------
# Mock heavy dependencies *before* importing routing so that the module
# can be loaded without Redis, git repos, or the full adapter tree.
# -----------------------------------------------------------------------
_LIB_DIR = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, _LIB_DIR)

_FAKE_CONFIG = {
    "adapters.active": [],
    "adapters.mandatory": [],
    "routing.main": [],
    "routing.pre": [],
    "routing.post": [],
    "routing.default": "unknown",
}

# -- fake config module -------------------------------------------------
_fake_config_mod = types.ModuleType("config")
_fake_config_mod.CONFIG = _FAKE_CONFIG  # type: ignore[attr-defined]

# -- fake adapter sub-modules -------------------------------------------
# routing.py imports adapter.cheat_sheets, adapter.cmd, etc. and also
# calls adapter.internal.InternalPages(...) and adapter.all_adapters().
# We need stub classes so the module-level _ROUTER = Router() succeeds.

class _StubAdapter:
    _adapter_name = "stub"
    _cache_needed = False

    def __init__(self, *args, **kwargs):
        pass

    def get_list(self, prefix=None):
        return []

    def is_found(self, topic):
        return False

    def is_cache_needed(self):
        return False

    def get_page_dict(self, query, request_options=None):
        return {}


class _StubInternalPages(_StubAdapter):
    _adapter_name = "internal"

    def __init__(self, get_topic_type=None, get_topics_list=None):
        self.get_topic_type = get_topic_type
        self.get_topics_list = get_topics_list


class _StubUnknownPages(_StubAdapter):
    _adapter_name = "unknown"

    def __init__(self, get_topic_type=None, get_topics_list=None):
        self.get_topic_type = get_topic_type
        self.get_topics_list = get_topics_list


_fake_adapter_internal = types.ModuleType("adapter.internal")
_fake_adapter_internal.InternalPages = _StubInternalPages  # type: ignore[attr-defined]
_fake_adapter_internal.UnknownPages = _StubUnknownPages  # type: ignore[attr-defined]

# Build the fake adapter package
_fake_adapter_mod = types.ModuleType("adapter")
_fake_adapter_mod.all_adapters = lambda as_dict=False: {}  # type: ignore[attr-defined]
_fake_adapter_mod.internal = _fake_adapter_internal  # type: ignore[attr-defined]
# Create stub sub-modules for every adapter imported by routing.py
for _sub in ["cheat_sheets", "cmd", "latenz", "learnxiny", "question", "rosetta"]:
    mod = types.ModuleType(f"adapter.{_sub}")
    setattr(_fake_adapter_mod, _sub, mod)

# -- fake cache module --------------------------------------------------
_fake_cache_mod = types.ModuleType("cache")
_fake_cache_mod.get = lambda *a, **kw: None  # type: ignore[attr-defined]
_fake_cache_mod.put = lambda *a, **kw: None  # type: ignore[attr-defined]
_fake_cache_mod.delete = lambda *a, **kw: None  # type: ignore[attr-defined]

# -- inject all fakes into sys.modules ----------------------------------
_saved_modules = {}
_for_patch = {
    "config": _fake_config_mod,
    "adapter": _fake_adapter_mod,
    "adapter.internal": _fake_adapter_internal,
    "cache": _fake_cache_mod,
}
for _sub in ["cheat_sheets", "cmd", "latenz", "learnxiny", "question", "rosetta"]:
    _for_patch[f"adapter.{_sub}"] = getattr(_fake_adapter_mod, _sub)

for name, mod in _for_patch.items():
    _saved_modules[name] = sys.modules.get(name)
    sys.modules[name] = mod

# -- import routing (creates the module-level _ROUTER) ------------------
import routing  # noqa: E402

# -- restore original modules -------------------------------------------
for name, orig in _saved_modules.items():
    if orig is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = orig


# -----------------------------------------------------------------------
# Helper: build a Router with its heavy __init__ bypassed
# -----------------------------------------------------------------------

def _make_router(topic_lists_by_adapter):
    """
    Create a real ``routing.Router`` instance whose ``get_topics_list``
    is the production implementation, but skip the expensive
    adapter-instantiation logic in ``__init__``.

    *topic_lists_by_adapter* maps adapter name to the list of topics
    it contributes, e.g.::

        {
            "internal": [":help", ":list", ":styles"],
            "cheat.sheets dir": ["python/", "go/"],
            "tldr": ["ls", "grep", "tar"],
        }
    """
    router = object.__new__(routing.Router)
    router._cached_topics_list = {}
    router._cached_topic_type = {}
    router._adapter = {k: None for k in topic_lists_by_adapter}
    router._topic_list = {k: list(v) for k, v in topic_lists_by_adapter.items()}
    router.routing_table = []
    return router


# ===================================================================
# Tests
# ===================================================================


class TestTopicsListCacheSeparation(unittest.TestCase):
    """
    Test that ``Router.get_topics_list`` maintains separate caches for
    different filter combinations.
    """

    def test_filtered_then_unfiltered_returns_full_list(self):
        """
        Scenario: a keyword search (skip_internal=True, skip_dirs=True) runs
        first, then the HTML datalist calls get_topics_list() with no filters.

        Expected: the second call must return the FULL list including
        internal topics and directory entries.
        """
        router = _make_router(
            {
                "internal": [":help", ":list", ":styles"],
                "cheat.sheets dir": ["python/", "go/"],
                "tldr": ["ls", "grep"],
            }
        )

        # First call: keyword search uses filters
        filtered = router.get_topics_list(skip_internal=True, skip_dirs=True)
        self.assertNotIn(":help", filtered)
        self.assertNotIn(":list", filtered)
        self.assertNotIn("python/", filtered)
        self.assertIn("ls", filtered)

        # Second call: HTML datalist wants everything
        full = router.get_topics_list()
        self.assertIn(":help", full, "internal topic :help missing from full list")
        self.assertIn(":list", full, "internal topic :list missing from full list")
        self.assertIn(":styles", full, "internal topic :styles missing from full list")
        self.assertIn("python/", full, "dir entry python/ missing from full list")
        self.assertIn("go/", full, "dir entry go/ missing from full list")
        self.assertIn("ls", full)

    def test_unfiltered_then_filtered_returns_filtered_list(self):
        """
        Scenario: the HTML datalist call happens first (no filters),
        then a keyword search calls with skip_internal=True, skip_dirs=True.

        Expected: the keyword search must get a FILTERED list that
        excludes internal topics and directory entries.
        """
        router = _make_router(
            {
                "internal": [":help", ":list"],
                "cheat.sheets dir": ["python/", "go/"],
                "tldr": ["ls", "grep"],
            }
        )

        # First call: unfiltered (HTML datalist)
        full = router.get_topics_list()
        self.assertIn(":help", full)
        self.assertIn("python/", full)

        # Second call: filtered (keyword search)
        filtered = router.get_topics_list(skip_internal=True, skip_dirs=True)
        self.assertNotIn(":help", filtered, "internal topic leaked into filtered list")
        self.assertNotIn(":list", filtered, "internal topic leaked into filtered list")
        self.assertNotIn(
            "python/", filtered, "dir entry leaked into filtered list"
        )
        self.assertIn("ls", filtered)
        self.assertIn("grep", filtered)

    def test_list_endpoint_after_search_includes_internal_topics(self):
        """
        Regression: after a keyword search, the /:list endpoint must still
        show internal topics like :help, :styles, :list.
        """
        internal_topics = [":help", ":list", ":styles", ":intro"]
        router = _make_router(
            {
                "internal": internal_topics,
                "cheat.sheets dir": ["python/"],
                "tldr": ["ls", "grep", "tar", "curl"],
            }
        )

        # Simulate a keyword search (filtered)
        router.get_topics_list(skip_internal=True, skip_dirs=True)

        # Simulate /:list endpoint (unfiltered)
        list_result = router.get_topics_list()
        for topic in internal_topics:
            self.assertIn(
                topic,
                list_result,
                f"internal topic {topic} missing from :list after search",
            )

    def test_unknown_topic_suggestions_after_search_include_internal(self):
        """
        Regression: after a keyword search, unknown topic suggestions
        (fuzzy matching) must still consider internal topics as candidates.

        If the cache were polluted, an unknown topic like ":hep" would
        not match ":help" because internal topics would be missing.
        """
        router = _make_router(
            {
                "internal": [":help", ":list", ":styles"],
                "tldr": ["ls", "grep"],
            }
        )

        # Simulate a keyword search first (filtered)
        router.get_topics_list(skip_internal=True, skip_dirs=True)

        # Now get the full list used by UnknownPages._get_page for suggestions
        full_list = router.get_topics_list()

        # Filter for ":" topics as UnknownPages does
        colon_topics = [x for x in full_list if x.startswith(":")]
        self.assertIn(
            ":help",
            colon_topics,
            ":help missing from suggestion candidates after search",
        )
        self.assertIn(
            ":list",
            colon_topics,
            ":list missing from suggestion candidates after search",
        )

    def test_random_after_search_can_select_internal_topics(self):
        """
        Regression: :random logic relies on get_topics_list() to find
        candidates.  After a keyword search, internal topics must still
        be present in the pool.
        """
        router = _make_router(
            {
                "internal": [":help", ":list"],
                "cheat.sheets dir": ["python/"],
                "tldr": ["ls", "grep", "tar"],
            }
        )

        # Simulate a keyword search first (filtered)
        router.get_topics_list(skip_internal=True, skip_dirs=True)

        # :random uses the unfiltered list
        full_list = router.get_topics_list()

        # handle_if_random_request filters these by removing "/" and ":",
        # but they must be *present* in the full list in the first place
        self.assertIn(":help", full_list)
        self.assertIn(":list", full_list)
        self.assertIn("python/", full_list)

    def test_all_four_cache_keys_are_independent(self):
        """
        Verify that all four combinations of (skip_internal, skip_dirs)
        produce independent cached results.
        """
        router = _make_router(
            {
                "internal": [":help"],
                "cheat.sheets dir": ["python/"],
                "tldr": ["ls"],
            }
        )

        result_none = router.get_topics_list()
        result_skip_internal = router.get_topics_list(skip_internal=True)
        result_skip_dirs = router.get_topics_list(skip_dirs=True)
        result_skip_both = router.get_topics_list(skip_internal=True, skip_dirs=True)

        # Full list has everything
        self.assertIn(":help", result_none)
        self.assertIn("python/", result_none)

        # skip_internal: no internal, but dirs present
        self.assertNotIn(":help", result_skip_internal)
        self.assertIn("python/", result_skip_internal)

        # skip_dirs: internal present, but no dirs
        self.assertIn(":help", result_skip_dirs)
        self.assertNotIn("python/", result_skip_dirs)

        # skip both: neither internal nor dirs
        self.assertNotIn(":help", result_skip_both)
        self.assertNotIn("python/", result_skip_both)

        # ls is always present
        for result in [
            result_none,
            result_skip_internal,
            result_skip_dirs,
            result_skip_both,
        ]:
            self.assertIn("ls", result)

    def test_cache_stability_repeated_calls(self):
        """
        Calling the same variant multiple times must return the same
        result (cache stability).
        """
        router = _make_router(
            {
                "internal": [":help", ":list"],
                "tldr": ["ls"],
            }
        )

        first = router.get_topics_list(skip_internal=True, skip_dirs=True)
        second = router.get_topics_list(skip_internal=True, skip_dirs=True)
        self.assertEqual(first, second)

        full_first = router.get_topics_list()
        full_second = router.get_topics_list()
        self.assertEqual(full_first, full_second)

    def test_fosdem_always_skipped(self):
        """
        fosdem is always excluded regardless of filter parameters.
        """
        router = _make_router(
            {
                "fosdem": ["fosdem-talk-1", "fosdem-talk-2"],
                "tldr": ["ls"],
            }
        )

        for kwargs in [
            {},
            {"skip_internal": True},
            {"skip_dirs": True},
            {"skip_internal": True, "skip_dirs": True},
        ]:
            result = router.get_topics_list(**kwargs)
            self.assertNotIn("fosdem-talk-1", result)
            self.assertNotIn("fosdem-talk-2", result)


if __name__ == "__main__":
    unittest.main()
