"""
Query diagnostic module for cheat.sh maintainers.

Given any topic, produces a full trace of how the query is processed:
normalization stages, topic type matching, adapter ordering, cache
configuration, and the reason for the final routing decision.

Exports:
    QueryDiagnostic       -- data class holding diagnostic results
    run_diagnosis(query)  -- run the full diagnostic pipeline
    render_ansi(diag)     -- terminal-readable output
    render_json(diag)     -- JSON string output
    to_dict(diag)         -- plain dict for serialization / HTML embedding
"""

import json


class QueryDiagnostic(object):
    """Holds all diagnostic information for a single query."""

    def __init__(self):
        self.raw_query = ""
        self.normalization_stages = {}
        self.parsed_topic = ""
        self.parsed_keyword = None
        self.search_mode = False
        self.explicit_topic_type = ""
        self.effective_topic = ""
        self.is_random = False
        self.random_resolved = ""
        self.routing_trace = []
        self.topic_types = []
        self.adapter_order = []
        self.cache_info = []
        self.resolution_reason = ""


def to_dict(diag):
    """Convert a QueryDiagnostic to a plain dictionary."""
    return {
        "raw_query": diag.raw_query,
        "normalization_stages": diag.normalization_stages,
        "parsed_topic": diag.parsed_topic,
        "parsed_keyword": diag.parsed_keyword,
        "search_mode": diag.search_mode,
        "explicit_topic_type": diag.explicit_topic_type,
        "effective_topic": diag.effective_topic,
        "is_random": diag.is_random,
        "random_resolved": diag.random_resolved,
        "routing_trace": diag.routing_trace,
        "topic_types": diag.topic_types,
        "adapter_order": diag.adapter_order,
        "cache_info": diag.cache_info,
        "resolution_reason": diag.resolution_reason,
    }


def render_json(diag):
    """Render a QueryDiagnostic as a formatted JSON string."""
    return json.dumps(to_dict(diag), indent=2, ensure_ascii=False)


def render_ansi(diag):
    """Render a QueryDiagnostic as colored terminal text."""
    try:
        import colored
        _has_colored = True
    except ImportError:
        _has_colored = False

    lines = []

    def _header(title):
        if _has_colored:
            return (
                colored.fg("cyan")
                + colored.attr("bold")
                + "\n\u2500\u2500 %s \u2500\u2500" % title
                + colored.attr("reset")
                + "\n"
            )
        return "\n-- %s --\n" % title

    def _label(text):
        if _has_colored:
            return colored.fg("yellow") + text + colored.attr("reset")
        return text

    def _value(text):
        if _has_colored:
            return colored.fg("white") + str(text) + colored.attr("reset")
        return str(text)

    def _good(text):
        if _has_colored:
            return colored.fg("green") + str(text) + colored.attr("reset")
        return str(text)

    def _bad(text):
        if _has_colored:
            return colored.fg("red") + str(text) + colored.attr("reset")
        return str(text)

    # ── Query ──
    lines.append(_header("Query"))
    lines.append("  %s: %s\n" % (_label("raw"), _value(diag.raw_query)))

    # ── Normalization ──
    lines.append(_header("Normalization"))
    for stage_name, stage_value in diag.normalization_stages.items():
        if stage_name == "raw":
            continue
        lines.append("  %s: %s\n" % (_label(stage_name), _value(stage_value)))
    lines.append("  %s: %s\n" % (_label("parsed_topic"), _value(diag.parsed_topic)))
    if diag.parsed_keyword is not None:
        lines.append("  %s: %s\n" % (_label("parsed_keyword"), _value(diag.parsed_keyword)))
        lines.append("  %s: %s\n" % (_label("search_mode"), _value(str(diag.search_mode))))

    # ── Topic Type Resolution ──
    lines.append(_header("Topic Type Resolution"))
    if diag.explicit_topic_type:
        lines.append("  %s: %s\n" % (_label("explicit_type"), _value(diag.explicit_topic_type)))
    lines.append("  %s: %s\n" % (_label("effective_topic"), _value(diag.effective_topic)))
    if diag.is_random:
        lines.append("  %s: %s\n" % (_label("random_resolved"), _value(diag.random_resolved)))
    lines.append("  %s: %s\n" % (
        _label("matched_types"),
        _good(", ".join(diag.topic_types)) if diag.topic_types else _bad("none"),
    ))

    # ── Routing Trace ──
    lines.append(_header("Routing Trace"))
    for entry in diag.routing_trace:
        regex = entry["regexp"] if entry["regexp"] else "(match-all)"
        matched = entry["regex_matched"]
        found = entry["is_found"]

        if matched and found is True:
            marker = _good("HIT")
        elif matched and found is False:
            marker = _bad("MISS")
        elif matched and found is None:
            marker = _value("MATCH(no adapter)")
        else:
            marker = "   "

        found_str = ""
        if found is not None:
            found_str = ", is_found=%s" % found

        lines.append("  %s  regex=%-30s  route=%-20s%s\n" % (
            marker, repr(regex), entry["route"], found_str,
        ))

    # ── Adapter Order ──
    lines.append(_header("Adapter Order"))
    if diag.adapter_order:
        for i, adapter_name in enumerate(diag.adapter_order, 1):
            lines.append("  %d. %s\n" % (i, _value(adapter_name)))
    else:
        lines.append("  %s\n" % _bad("(none)"))

    # ── Cache Info ──
    lines.append(_header("Cache Info"))
    if diag.cache_info:
        for info in diag.cache_info:
            needed_str = _good("yes") if info["cache_needed"] else _value("no")
            lines.append("  %s: cache_needed=%s, key_pattern=%s\n" % (
                _label(info["adapter"]), needed_str, _value(info["cache_key_pattern"]),
            ))
    else:
        lines.append("  %s\n" % _value("(no adapters to cache)"))

    # ── Resolution ──
    lines.append(_header("Resolution"))
    if diag.topic_types and diag.topic_types[0] in ("unknown", "question"):
        lines.append("  %s\n" % _bad(diag.resolution_reason))
    else:
        lines.append("  %s\n" % _good(diag.resolution_reason))

    return "".join(lines)


def run_diagnosis(raw_query):
    """
    Run the full diagnostic pipeline for `raw_query`.

    Returns a QueryDiagnostic instance.
    """
    from cheat_wrapper import normalize_query
    from routing import _ROUTER

    diag = QueryDiagnostic()
    diag.raw_query = raw_query

    # Step 1: Normalize the query through the full pipeline
    topic, keyword, search_options, stages = normalize_query(raw_query)
    diag.normalization_stages = stages
    diag.parsed_topic = topic
    diag.parsed_keyword = keyword
    diag.search_mode = bool(keyword)

    # Step 2: Delegate to the Router for routing diagnosis
    router_result = _ROUTER.diagnose(topic)
    diag.explicit_topic_type = router_result["explicit_topic_type"]
    diag.effective_topic = router_result["effective_topic"]
    diag.is_random = router_result["is_random"]
    diag.random_resolved = router_result["random_resolved"]
    diag.routing_trace = router_result["routing_trace"]
    diag.topic_types = router_result["topic_types"]
    diag.adapter_order = router_result["adapter_order"]
    diag.cache_info = router_result["cache_info"]
    diag.resolution_reason = router_result["resolution_reason"]

    return diag
