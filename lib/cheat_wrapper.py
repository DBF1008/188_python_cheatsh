"""
Main cheat.sh wrapper.
Parse the query, get answers from getters (using get_answer),
visualize it using frontends and return the result.

Exports:

    cheat_wrapper()
    normalize_query()
"""

import re
import json

from routing import get_answers, get_topics_list
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


def _sanitize_query(query):
    return re.sub('[<>"]', "", query)


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


def normalize_query(query):
    """
    Run the full normalization pipeline on `query`.

    Returns:
        (topic, keyword, search_options, stages)
    where `stages` is a dict recording the query after each step:
        raw, sanitized, section_added, aliases_rewritten,
        section_rewritten, final
    """
    stages = {"raw": query}
    query = _sanitize_query(query)
    stages["sanitized"] = query
    query = _add_section_name(query)
    stages["section_added"] = query
    query = _rewrite_aliases(query)
    stages["aliases_rewritten"] = query
    query = _rewrite_section_name(query)
    stages["section_rewritten"] = query
    topic, keyword, search_options = _parse_query(query)
    stages["final"] = query
    return topic, keyword, search_options, stages


def cheat_wrapper(query, request_options=None, output_format="ansi"):
    """
    Function that delivers cheat sheet for `query`.
    If `html` is True, the answer is formatted as HTML.
    Additional request options specified in `request_options`.

    Returns:
        (result, found) tuple
    """

    # Handle :debug/<topic> diagnostic mode
    if query.startswith(":debug/") or query == ":debug":
        from diagnose import run_diagnosis, render_ansi as diag_render_ansi
        from diagnose import render_json as diag_render_json

        debug_topic = query[7:] if len(query) > 7 else ""
        diag = run_diagnosis(debug_topic)
        if output_format == "json":
            return diag_render_json(diag), True
        return diag_render_ansi(diag), True

    topic, keyword, search_options, _stages = normalize_query(query)

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
        return json.dumps(answer_data, indent=4), True
    return frontend.ansi.visualize(answer_data, request_options)
