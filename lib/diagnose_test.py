"""
Tests for the query diagnostic module (diagnose.py).

Covers:
    1. Normal cheatsheet query (topic found by a data adapter)
    2. Explicit topic_type query (tldr:ls style)
    3. Unknown single-word topic (falls to 'unknown' adapter)
    4. Multi-word query (falls to 'question' default)
"""

import os
import sys
import pytest

# Ensure lib/ is on the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router_with_mocks(cheat_sheets_topics=None, tldr_topics=None):
    """
    Create a Router with adapter _get_list mocked to avoid filesystem access.

    By default all adapters return empty topic lists (is_found → False).
    Pass lists to `cheat_sheets_topics` / `tldr_topics` to simulate matches.
    """
    from adapter.adapter import Adapter
    from adapter.git_adapter import RepositoryAdapter
    from adapter.cheat_sheets import CheatSheets, CheatSheetsDir
    from adapter.cheat_cheat import Cheat
    from adapter.tldr import Tldr
    from adapter.learnxiny import LearnXinY
    from adapter.rosetta import Rosetta
    from adapter.latenz import Latenz

    # We must mock _get_list on every class that defines/overrides it,
    # because Python MRO resolves to the most-derived override.
    _mock_targets = [
        (Adapter, lambda self, prefix=None: []),
        (RepositoryAdapter, lambda self, prefix=None: []),
        (CheatSheets, lambda self, prefix=None: cheat_sheets_topics or []),
        (CheatSheetsDir, lambda self, prefix=None: []),
        (Cheat, lambda self, prefix=None: []),
        (Tldr, lambda self, prefix=None: tldr_topics or []),
        (LearnXinY, lambda self, prefix=None: []),
        (Rosetta, lambda self, prefix=None: []),
        (Latenz, lambda self, prefix=None: []),
    ]

    originals = {}
    for cls, mock_fn in _mock_targets:
        if hasattr(cls, "_get_list"):
            originals[cls] = cls._get_list
            cls._get_list = mock_fn

    try:
        from routing import Router
        router = Router()
    finally:
        for cls, orig in originals.items():
            cls._get_list = orig

    return router


# ---------------------------------------------------------------------------
# Test 1: Normal cheatsheet query — topic found by a data adapter
# ---------------------------------------------------------------------------

class TestNormalCheatsheetQuery:

    def test_normalization_preserves_simple_topic(self):
        from diagnose import run_diagnosis
        router = _make_router_with_mocks(cheat_sheets_topics=["ls"])

        # We call Router.diagnose directly to test routing
        result = router.diagnose("ls")

        assert result["effective_topic"] == "ls"
        assert result["explicit_topic_type"] == ""
        assert result["is_random"] is False

    def test_topic_types_include_real_adapter(self):
        router = _make_router_with_mocks(cheat_sheets_topics=["ls"])
        result = router.diagnose("ls")

        # cheat.sheets should be in the matched types
        assert "cheat.sheets" in result["topic_types"]
        # Should NOT be 'unknown' or 'question'
        assert "unknown" not in result["topic_types"]
        assert "question" not in result["topic_types"]

    def test_adapter_order_is_nonempty(self):
        router = _make_router_with_mocks(cheat_sheets_topics=["ls"])
        result = router.diagnose("ls")

        assert len(result["adapter_order"]) > 0
        assert "cheat.sheets" in result["adapter_order"]

    def test_routing_trace_has_entries(self):
        router = _make_router_with_mocks(cheat_sheets_topics=["ls"])
        result = router.diagnose("ls")

        assert len(result["routing_trace"]) > 0
        # The trace should show cheat.sheets as a hit
        cheat_sheets_entries = [
            e for e in result["routing_trace"]
            if e["route"] == "cheat.sheets"
        ]
        assert len(cheat_sheets_entries) > 0
        assert cheat_sheets_entries[0]["regex_matched"] is True
        assert cheat_sheets_entries[0]["is_found"] is True

    def test_cache_info_present(self):
        router = _make_router_with_mocks(cheat_sheets_topics=["ls"])
        result = router.diagnose("ls")

        assert len(result["cache_info"]) > 0
        cs_info = [c for c in result["cache_info"] if c["adapter"] == "cheat.sheets"]
        assert len(cs_info) == 1
        assert cs_info[0]["cache_key_pattern"] == "cheat.sheets:ls"

    def test_resolution_reason_matched(self):
        router = _make_router_with_mocks(cheat_sheets_topics=["ls"])
        result = router.diagnose("ls")

        assert "Matched" in result["resolution_reason"]
        assert "cheat.sheets" in result["resolution_reason"]


# ---------------------------------------------------------------------------
# Test 2: Explicit topic_type query — tldr:ls
# ---------------------------------------------------------------------------

class TestExplicitTopicType:

    def test_explicit_type_parsed(self):
        router = _make_router_with_mocks(tldr_topics=["ls"])
        result = router.diagnose("tldr:ls")

        assert result["explicit_topic_type"] == "tldr"
        assert result["effective_topic"] == "ls"

    def test_topic_types_filtered_to_explicit(self):
        router = _make_router_with_mocks(
            cheat_sheets_topics=["ls"],
            tldr_topics=["ls"],
        )
        result = router.diagnose("tldr:ls")

        # Even though cheat.sheets also has "ls", the explicit prefix
        # restricts to just tldr
        assert result["topic_types"] == ["tldr"]

    def test_adapter_order_is_single_explicit(self):
        router = _make_router_with_mocks(tldr_topics=["ls"])
        result = router.diagnose("tldr:ls")

        assert result["adapter_order"] == ["tldr"]

    def test_cache_info_for_explicit_type(self):
        router = _make_router_with_mocks(tldr_topics=["ls"])
        result = router.diagnose("tldr:ls")

        assert len(result["cache_info"]) == 1
        assert result["cache_info"][0]["adapter"] == "tldr"
        assert result["cache_info"][0]["cache_key_pattern"] == "tldr:ls"


# ---------------------------------------------------------------------------
# Test 3: Unknown single-word topic — falls to 'unknown' adapter
# ---------------------------------------------------------------------------

class TestUnknownTopic:

    def test_unknown_topic_type(self):
        # No adapter has "xyzzyplugh" → routing.post regex ^[^/ +]*$ matches
        # → unknown adapter (is_found always True)
        router = _make_router_with_mocks()
        result = router.diagnose("xyzzyplugh")

        assert result["topic_types"] == ["unknown"]

    def test_adapter_order_is_unknown(self):
        router = _make_router_with_mocks()
        result = router.diagnose("xyzzyplugh")

        assert result["adapter_order"] == ["unknown"]

    def test_resolution_reason_explains_unknown(self):
        router = _make_router_with_mocks()
        result = router.diagnose("xyzzyplugh")

        assert "unknown" in result["resolution_reason"].lower()

    def test_routing_trace_shows_unknown_match(self):
        router = _make_router_with_mocks()
        result = router.diagnose("xyzzyplugh")

        unknown_entries = [
            e for e in result["routing_trace"]
            if e["route"] == "unknown"
        ]
        assert len(unknown_entries) > 0
        assert unknown_entries[0]["regex_matched"] is True
        assert unknown_entries[0]["is_found"] is True

    def test_data_adapters_not_matched(self):
        router = _make_router_with_mocks()
        result = router.diagnose("xyzzyplugh")

        # No data adapter should have matched
        for entry in result["routing_trace"]:
            if entry["route"] in ("cheat.sheets", "cheat", "tldr", "learnxiny"):
                # regex matches (empty string matches everything) but is_found is False
                assert entry["is_found"] is not True


# ---------------------------------------------------------------------------
# Test 4 (bonus): Multi-word query → 'question' default fallback
# ---------------------------------------------------------------------------

class TestMultiWordQuestionFallback:

    def test_multi_word_falls_to_question(self):
        # "python copy file" → normalized to "python/copy file"
        # Contains "/" → routing.post regex ^[^/ +]*$ does NOT match
        # No adapter matches → default "question"
        router = _make_router_with_mocks()
        result = router.diagnose("python/copy file")

        assert result["topic_types"] == ["question"]

    def test_resolution_reason_explains_question(self):
        router = _make_router_with_mocks()
        result = router.diagnose("python/copy file")

        assert "question" in result["resolution_reason"].lower()

    def test_routing_trace_no_matches(self):
        router = _make_router_with_mocks()
        result = router.diagnose("python/copy file")

        # No routing entry should have both regex_matched=True and is_found=True
        actual_hits = [
            e for e in result["routing_trace"]
            if e["regex_matched"] and e["is_found"] is True
        ]
        assert len(actual_hits) == 0


# ---------------------------------------------------------------------------
# Test 5: Rendering output
# ---------------------------------------------------------------------------

class TestRendering:

    def test_render_ansi_produces_output(self):
        from diagnose import QueryDiagnostic, render_ansi

        diag = QueryDiagnostic()
        diag.raw_query = "ls"
        diag.normalization_stages = {"raw": "ls", "final": "ls"}
        diag.parsed_topic = "ls"
        diag.effective_topic = "ls"
        diag.topic_types = ["cheat.sheets"]
        diag.adapter_order = ["cheat.sheets"]
        diag.routing_trace = [
            {"regexp": "", "route": "cheat.sheets", "regex_matched": True, "is_found": True},
        ]
        diag.cache_info = [
            {"adapter": "cheat.sheets", "cache_needed": False, "cache_key_pattern": "cheat.sheets:ls"},
        ]
        diag.resolution_reason = "Matched 1 adapter(s): cheat.sheets"

        output = render_ansi(diag)
        assert isinstance(output, str)
        assert len(output) > 0
        assert "ls" in output
        assert "cheat.sheets" in output

    def test_render_json_produces_valid_json(self):
        import json
        from diagnose import QueryDiagnostic, render_json

        diag = QueryDiagnostic()
        diag.raw_query = "ls"
        diag.normalization_stages = {"raw": "ls", "final": "ls"}
        diag.parsed_topic = "ls"
        diag.effective_topic = "ls"
        diag.topic_types = ["cheat.sheets"]
        diag.adapter_order = ["cheat.sheets"]
        diag.routing_trace = []
        diag.cache_info = []
        diag.resolution_reason = "Matched 1 adapter(s): cheat.sheets"

        output = render_json(diag)
        parsed = json.loads(output)
        assert parsed["raw_query"] == "ls"
        assert parsed["topic_types"] == ["cheat.sheets"]

    def test_to_dict_roundtrip(self):
        import json
        from diagnose import QueryDiagnostic, to_dict

        diag = QueryDiagnostic()
        diag.raw_query = "test"
        diag.topic_types = ["tldr"]

        d = to_dict(diag)
        assert isinstance(d, dict)
        assert d["raw_query"] == "test"
        assert d["topic_types"] == ["tldr"]
        # Should be JSON-serializable
        json.dumps(d)


# ---------------------------------------------------------------------------
# Test 6: normalize_query stage capture
# ---------------------------------------------------------------------------

class TestNormalizeQuery:

    def test_stages_captured(self):
        from cheat_wrapper import normalize_query

        topic, keyword, search_options, stages = normalize_query("python copy file")

        assert "raw" in stages
        assert stages["raw"] == "python copy file"
        assert "sanitized" in stages
        assert "section_added" in stages
        assert "aliases_rewritten" in stages
        assert "section_rewritten" in stages
        assert "final" in stages

    def test_section_name_added(self):
        from cheat_wrapper import normalize_query

        topic, keyword, search_options, stages = normalize_query("python copy file")

        # "python copy file" → "python/copy file"
        assert stages["section_added"] == "python/copy file"

    def test_alias_rewrite(self):
        from cheat_wrapper import normalize_query

        topic, keyword, search_options, stages = normalize_query(":bash.completion")

        assert stages["aliases_rewritten"] == ":bash_completion"

    def test_keyword_extraction(self):
        from cheat_wrapper import normalize_query

        topic, keyword, search_options, stages = normalize_query("python~shutil")

        assert topic == "python"
        assert keyword == "shutil"
        assert stages["final"] == "python~shutil"
