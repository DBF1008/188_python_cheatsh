"""
Main cheat.sh wrapper.
Parse the query, get answers from getters (using get_answer),
visualize it using frontends and return the result.

Exports:

    cheat_wrapper()
"""

import json

from routing import get_answers, get_topics_list
from search import find_answers_by_keyword
from query import ParsedQuery
import postprocessing

import frontend.html
import frontend.ansi


def cheat_wrapper(query, request_options=None, output_format="ansi"):
    """
    Function that delivers cheat sheet for `query`.
    If `html` is True, the answer is formatted as HTML.
    Additional request options specified in `request_options`.
    """

    parsed = ParsedQuery.from_query(query)

    if parsed.is_search:
        answers = find_answers_by_keyword(
            parsed.topic,
            parsed.keyword,
            options=parsed.search_options,
            request_options=request_options,
        )
    else:
        answers = get_answers(parsed.topic, request_options=request_options)

    answers = [
        postprocessing.postprocess(
            answer,
            parsed.keyword,
            parsed.search_options,
            request_options=request_options,
        )
        for answer in answers
    ]

    answer_data = {
        "query": parsed.query,
        "keyword": parsed.keyword,
        "answers": answers,
    }

    if output_format == "html":
        answer_data["topics_list"] = get_topics_list()
        return frontend.html.visualize(answer_data, request_options)
    elif output_format == "json":
        return json.dumps(answer_data, indent=4)
    return frontend.ansi.visualize(answer_data, request_options)
