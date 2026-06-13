"""
Main cheat.sh wrapper.
Parse the query, get answers from getters (using get_answer),
visualize it using frontends and return the result.

Exports:

    cheat_wrapper()
    query_diagnostics()
    format_diagnostics_text()
"""

import re
import json

from routing import get_answers, get_topics_list, get_query_diagnostics
from search import find_answers_by_keyword
from languages_data import LANGUAGE_ALIAS, rewrite_editor_section_name
import postprocessing

import frontend.html
import frontend.ansi


def _add_section_name(query):
    # temporary solution before we don't find a fixed one
    if " " not in query and "+" not in query:
        return query
    if "/" in query:
        return query
    if " " in query:
        return re.sub(r" +", "/", query, count=1)
    if "+" in query:
        # replace only single + to avoid catching g++ and friends
        return re.sub(r"([^\+])\+([^\+])", r"\1/\2", query, count=1)


def _sanitize_query(query):
    return re.sub('[<>"]', "", query)


def _rewrite_aliases(word):
    if word == ":bash.completion":
        return ":bash_completion"
    return word


def _rewrite_section_name(query):
    """
    Rewriting special section names:
    * EDITOR:NAME => emacs:go-mode
    """

    if "/" not in query:
        return query

    section_name, rest = query.split("/", 1)

    if ":" in section_name:
        section_name = rewrite_editor_section_name(section_name)
    section_name = LANGUAGE_ALIAS.get(section_name, section_name)

    return "%s/%s" % (section_name, rest)


def _parse_query(query):
    topic = query
    keyword = None
    search_options = ""

    keyword = None
    if "~" in query:
        topic = query
        pos = topic.index("~")
        keyword = topic[pos + 1 :]
        topic = topic[:pos]

        if "/" in keyword:
            search_options = keyword[::-1]
            search_options = search_options[: search_options.index("/")]
            keyword = keyword[: -len(search_options) - 1]

    return topic, keyword, search_options


def _normalize_query(query):
    """
    Apply the query normalization pipeline and return
    (normalized_query, steps), where `steps` records the result of each stage.
    Used both by cheat_wrapper() and by query_diagnostics() so that the
    diagnostics report exactly what the normal request path does.
    """

    sanitized = _sanitize_query(query)
    section_added = _add_section_name(sanitized)
    alias_rewritten = _rewrite_aliases(section_added)
    section_rewritten = _rewrite_section_name(alias_rewritten)

    steps = {
        "sanitized": sanitized,
        "section_added": section_added,
        "alias_rewritten": alias_rewritten,
        "section_rewritten": section_rewritten,
        "final": section_rewritten,
    }
    return section_rewritten, steps


def cheat_wrapper(query, request_options=None, output_format="ansi"):
    """
    Function that delivers cheat sheet for `query`.
    If `html` is True, the answer is formatted as HTML.
    Additional request options specified in `request_options`.
    """

    # Maintainer-facing query diagnostics, triggered with ?debug=1.
    # query_diagnostics() runs the same normalization pipeline itself,
    # so we branch on the raw query before normalizing here.
    if request_options and request_options.get("debug"):
        return query_diagnostics(
            query, request_options=request_options, output_format=output_format
        )

    query, _steps = _normalize_query(query)

    # at the moment, we just remove trailing slashes
    # so queries python/ and python are equal
    # query = _strip_hyperlink(query.rstrip('/'))
    topic, keyword, search_options = _parse_query(query)

    if keyword:
        answers = find_answers_by_keyword(
            topic, keyword, options=search_options, request_options=request_options
        )
    else:
        answers = get_answers(topic, request_options=request_options)

    answers = [
        postprocessing.postprocess(
            answer, keyword, search_options, request_options=request_options
        )
        for answer in answers
    ]

    answer_data = {
        "query": query,
        "keyword": keyword,
        "answers": answers,
    }

    if output_format == "html":
        answer_data["topics_list"] = get_topics_list()
        return frontend.html.visualize(answer_data, request_options)
    elif output_format == "json":
        return json.dumps(answer_data, indent=4)
    return frontend.ansi.visualize(answer_data, request_options)


def query_diagnostics(query, request_options=None, output_format="ansi"):
    """
    Maintainer-facing query diagnostics.

    Return a structured, format-agnostic view of how `query` is normalized
    and routed (see routing.get_query_diagnostics): the normalized topic, the
    matched topic types, the final adapter order, cache hit/miss and the reason
    a query lands on the internal / unknown / question branches.

    The same diagnostics data is reused across output formats:
    * `json`        -> the structured dict, dumped as JSON (a string)
    * `html`        -> rendered text fed through the existing HTML frontend
    * `ansi` (else) -> rendered text fed through the existing ANSI frontend

    Returns a (result, found) tuple for ansi/html (like cheat_wrapper) and a
    JSON string for json.
    """

    normalized_query, steps = _normalize_query(query)
    topic, keyword, search_options = _parse_query(normalized_query)

    diag = {
        "input_query": query,
        "normalization": steps,
        "parsed": {
            "topic": topic,
            "keyword": keyword,
            "search_options": search_options,
            "search_mode": bool(keyword),
        },
        "routing": get_query_diagnostics(topic, request_options=request_options),
    }

    if output_format == "json":
        return json.dumps(diag, indent=4)

    text = format_diagnostics_text(diag)
    answer_data = {
        "query": normalized_query,
        "keyword": None,
        "answers": [
            {
                "topic": topic or query,
                "topic_type": "diagnostics",
                "answer": text,
                "format": "text",
            }
        ],
    }

    if output_format == "html":
        answer_data["topics_list"] = get_topics_list()
        return frontend.html.visualize(answer_data, request_options or {})
    return frontend.ansi.visualize(answer_data, request_options or {})


def format_diagnostics_text(diag):
    """
    Render the diagnostics dict (see query_diagnostics) as maintainer-readable
    plain text, suitable for terminal output.
    """

    def _or_none(value):
        if value is None or value == "":
            return "(none)"
        return value

    def _yn(value):
        return "yes" if value else "no"

    norm = diag["normalization"]
    parsed = diag["parsed"]
    routing = diag["routing"]
    branch = routing["branch"]

    lines = ["Query diagnostics for: %s" % diag["input_query"], ""]

    lines.append("[Normalization]")
    lines.append("  sanitized:         %s" % _or_none(norm["sanitized"]))
    lines.append("  section added:     %s" % _or_none(norm["section_added"]))
    lines.append("  alias rewritten:   %s" % _or_none(norm["alias_rewritten"]))
    lines.append("  section rewritten: %s" % _or_none(norm["section_rewritten"]))
    lines.append("  final:             %s" % _or_none(norm["final"]))
    lines.append("")

    lines.append("[Parsing]")
    lines.append("  topic:          %s" % _or_none(parsed["topic"]))
    lines.append("  keyword:        %s" % _or_none(parsed["keyword"]))
    lines.append("  search options: %s" % _or_none(parsed["search_options"]))
    lines.append("  search mode:    %s" % _yn(parsed["search_mode"]))
    if parsed["search_mode"]:
        lines.append(
            "  note:           keyword search uses the 'search' path, not get_answers;"
        )
        lines.append("                  routing below reflects the topic part only.")
    lines.append("")

    lines.append("[Routing]")
    lines.append("  routed topic:        %s" % _or_none(routing["topic_after_random"]))
    explicit = routing["explicit_topic_type"]
    if explicit:
        suffix = (
            " (applied)"
            if routing["explicit_applied"]
            else " (ignored: not in matched types)"
        )
    else:
        suffix = ""
    lines.append("  explicit topic_type: %s%s" % (_or_none(explicit), suffix))
    lines.append("  random request:      %s" % _yn(routing["random_request"]))
    lines.append("")
    lines.append("  routing table trace:")
    for row in routing["routing_table_trace"]:
        tag = "match" if row["regex_matched"] else "skip "
        if row["is_adapter"]:
            if row["regex_matched"]:
                found_str = "is_found=%s" % _yn(row["is_found"])
            else:
                found_str = "is_found=-"
        else:
            found_str = "(non-adapter route)"
        selected = " [SELECTED]" if row["selected"] else ""
        lines.append(
            "    %s  %-26s -> %-18s %s%s"
            % (tag, repr(row["regexp"]), row["route"], found_str, selected)
        )
    lines.append("")
    lines.append(
        "  raw selected:        %s" % (", ".join(routing["raw_selected"]) or "(none)")
    )
    if routing["trimmed_last"]:
        lines.append(
            "  note:                last selected route dropped (more than one matched)"
        )
    lines.append("  default applied:     %s" % _yn(routing["default_applied"]))
    lines.append(
        "  final adapter order: %s" % (", ".join(routing["adapter_order"]) or "(none)")
    )
    lines.append("")

    lines.append("[Cache]")
    if not routing["cache"]:
        lines.append("  (no cacheable entries)")
    for entry in routing["cache"]:
        lines.append(
            "  %-30s needed=%-3s hit=%-3s status=%s"
            % (
                entry["cache_entry_name"],
                _yn(entry["cache_needed"]),
                _yn(entry["cache_hit"]),
                entry["cache_status"],
            )
        )
    lines.append("")

    lines.append("[Branch]")
    lines.append("  primary topic_type: %s" % _or_none(branch["primary_topic_type"]))
    lines.append(
        "  internal=%s  unknown=%s  question=%s"
        % (_yn(branch["is_internal"]), _yn(branch["is_unknown"]), _yn(branch["is_question"]))
    )
    lines.append("  reason: %s" % branch["reason"])

    return "\n".join(lines) + "\n"
