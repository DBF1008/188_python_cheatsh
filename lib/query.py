"""
Shared query parsing and normalization.

Both the web frontend (``bin/app.py``) and the standalone CLI
(``lib/standalone.py``) turn raw user input into a :class:`ParsedQuery` via
:meth:`ParsedQuery.from_query`, so the normalization semantics live in exactly
one place instead of being spread across the entry points and the wrapper:

    * default topic for empty input  (``default_topic`` / ``DEFAULT_TOPIC``)
    * sanitizing of unsafe characters
    * section-name insertion          (``add_section_name``)
    * alias rewriting                 (``:bash.completion`` -> ``:bash_completion``)
    * editor/language section rewriting
    * ``~`` search splitting into topic / keyword / search options

Exports:

    DEFAULT_TOPIC
    default_topic()
    add_section_name()
    ParsedQuery
"""

import re

from languages_data import LANGUAGE_ALIAS, rewrite_editor_section_name

DEFAULT_TOPIC = ":firstpage"


def default_topic(topic):
    """
    Return `topic`, substituting `DEFAULT_TOPIC` for empty input (``None`` or "").
    """
    return topic or DEFAULT_TOPIC


def add_section_name(query):
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


def _sanitize(query):
    return re.sub('[<>"]', "", query)


def _rewrite_aliases(query):
    if query == ":bash.completion":
        return ":bash_completion"
    return query


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


def _split_search(query):
    """
    Split `query` into (topic, keyword, search_options).

    A ``~`` separates the topic from the search keyword; trailing ``/options``
    after the keyword (e.g. ``python~lambda/i``) are pulled out as search options.
    """

    topic = query
    keyword = None
    search_options = ""

    if "~" in query:
        pos = topic.index("~")
        keyword = topic[pos + 1 :]
        topic = topic[:pos]

        if "/" in keyword:
            search_options = keyword[::-1]
            search_options = search_options[: search_options.index("/")]
            keyword = keyword[: -len(search_options) - 1]

    return topic, keyword, search_options


class ParsedQuery(object):
    """
    Structured representation of a user query after normalization.

    Attributes:
        query (str):           the normalized full query string
        topic (str):           the topic to look up
        keyword (str|None):    search keyword, or ``None`` for a plain lookup
        search_options (str):  search option flags (e.g. ``i``, ``b``, ``r``)
    """

    def __init__(self, query, topic, keyword, search_options):
        self.query = query
        self.topic = topic
        self.keyword = keyword
        self.search_options = search_options

    @property
    def is_search(self):
        """Whether the query is a keyword search rather than a plain lookup."""
        return self.keyword is not None

    def __repr__(self):
        return "ParsedQuery(query=%r, topic=%r, keyword=%r, search_options=%r)" % (
            self.query,
            self.topic,
            self.keyword,
            self.search_options,
        )

    @classmethod
    def from_query(cls, query):
        """
        Build a :class:`ParsedQuery` from raw input by running the full
        normalization pipeline (default topic, sanitize, section-name insertion,
        alias rewrite, section rewrite, ``~`` search split).
        """

        query = default_topic(query)
        query = _sanitize(query)
        query = add_section_name(query)
        query = _rewrite_aliases(query)
        query = _rewrite_section_name(query)

        topic, keyword, search_options = _split_search(query)
        return cls(query, topic, keyword, search_options)
