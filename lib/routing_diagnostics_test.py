"""
Tests for the query routing diagnostics (read-only).

`cache.type` is forced to "none" before importing the routed modules, so the
cache probe is deterministic (status "disabled") and no redis backend is
required. Content-adapter routing is made deterministic without fetched
upstream data by injecting a synthetic topic into the cheat.sheets adapter.
"""

import json

import pytest

import config

config.CONFIG["cache.type"] = "none"

import routing
import cheat_wrapper


SYNTH_TOPIC = "zzdiagcheatzz"


@pytest.fixture(autouse=True)
def _diag_env():
    """
    Inject a synthetic root topic into the cheat.sheets adapter and reset the
    router's topic-type cache for isolation. Everything is restored afterwards.
    """
    adapter = routing._ROUTER._adapter["cheat.sheets"]
    saved_list = adapter._list[None]
    saved_cache = routing._ROUTER._cached_topic_type

    adapter._list[None] = list(saved_list) + [SYNTH_TOPIC]
    routing._ROUTER._cached_topic_type = {}
    try:
        yield
    finally:
        adapter._list[None] = saved_list
        routing._ROUTER._cached_topic_type = saved_cache


def test_normal_cheatsheet_query():
    diag = routing.get_query_diagnostics(SYNTH_TOPIC)

    assert diag["adapter_order"], "expected at least one adapter"
    assert diag["adapter_order"][0] == "cheat.sheets"
    assert diag["default_applied"] is False
    assert diag["branch"]["is_unknown"] is False
    assert diag["branch"]["is_question"] is False
    assert diag["branch"]["primary_topic_type"] == "cheat.sheets"

    # cache probe is read-only and deterministic with cache.type == "none"
    for entry in diag["cache"]:
        assert entry["cache_hit"] is False
        assert entry["cache_status"] in ("disabled", "miss")


def test_explicit_topic_type_query():
    diag = routing.get_query_diagnostics("cheat.sheets:" + SYNTH_TOPIC)

    assert diag["explicit_topic_type"] == "cheat.sheets"
    assert diag["topic_after_type_split"] == SYNTH_TOPIC
    assert diag["explicit_applied"] is True
    assert diag["adapter_order"] == ["cheat.sheets"]
    assert diag["topic_types"] == ["cheat.sheets"]


def test_unknown_topic_query():
    diag = routing.get_query_diagnostics("zzunknownzz123")

    assert diag["topic_types"] == ["unknown"]
    assert diag["default_applied"] is False
    assert diag["branch"]["is_unknown"] is True
    assert diag["branch"]["is_question"] is False

    # only the catch-all "unknown" post route should have been selected
    selected = [row["route"] for row in diag["routing_table_trace"] if row["selected"]]
    assert selected == ["unknown"]


def test_question_default_branch():
    # a slashed topic that is not a known root: fails the "^[^/ +]*$" unknown
    # rule and is not found by any content adapter, so it falls to the default
    diag = routing.get_query_diagnostics("zzdiag/zzz")

    assert diag["default_applied"] is True
    assert diag["topic_types"] == ["question"]
    assert diag["branch"]["is_question"] is True
    assert diag["raw_selected"] == []


def test_json_output_roundtrips():
    out = cheat_wrapper.query_diagnostics(SYNTH_TOPIC, output_format="json")

    assert isinstance(out, str)
    data = json.loads(out)
    assert "normalization" in data
    assert "routing" in data
    assert data["parsed"]["topic"] == SYNTH_TOPIC
    assert data["routing"]["adapter_order"][0] == "cheat.sheets"


def test_debug_trigger_via_cheat_wrapper():
    # ?debug=1 routes cheat_wrapper into the diagnostics path
    out = cheat_wrapper.cheat_wrapper(
        SYNTH_TOPIC, request_options={"debug": "1"}, output_format="json"
    )

    assert isinstance(out, str)
    data = json.loads(out)
    assert "routing" in data
    assert data["routing"]["branch"]["primary_topic_type"] == "cheat.sheets"


def test_text_render_ansi():
    result, found = cheat_wrapper.query_diagnostics(SYNTH_TOPIC, output_format="ansi")

    assert found is True
    assert SYNTH_TOPIC in result
    for header in ("[Normalization]", "[Routing]", "[Cache]", "[Branch]"):
        assert header in result
