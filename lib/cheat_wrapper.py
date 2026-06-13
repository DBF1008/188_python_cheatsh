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
import postprocessing
from query import parse_query, add_section_name as _add_section_name

import frontend.html
import frontend.ansi


def cheat_wrapper(query, request_options=None, output_format="ansi"):
    """
    Function that delivers cheat sheet for `query`.
    If `html` is True, the answer is formatted as HTML.
    Additional request options specified in `request_options`.
    """

    pq = parse_query(query)

    if pq.keyword:
        answers = find_answers_by_keyword(
            pq.topic,
            pq.keyword,
            options=pq.search_options,
            request_options=request_options,
        )
    else:
        answers = get_answers(pq.topic, request_options=request_options)

    answers = [
        postprocessing.postprocess(
            answer, pq.keyword, pq.search_options, request_options=request_options
        )
        for answer in answers
    ]

    answer_data = {
        "query": pq.topic,
        "keyword": pq.keyword,
        "answers": answers,
    }

    if output_format == "html":
        answer_data["topics_list"] = get_topics_list()
        return frontend.html.visualize(answer_data, request_options)
    elif output_format == "json":
        return json.dumps(answer_data, indent=4)
    return frontend.ansi.visualize(answer_data, request_options)
