"""
Unified query parsing and normalization pipeline.

This module centralizes all query parsing logic that was previously
scattered across cheat_wrapper.py, standalone.py, and bin/app.py.
Both the Web and standalone entry points should use this module
to ensure consistent query semantics.

Exports:

    DEFAULT_TOPIC       -- default topic when no query is provided
    ParsedQuery         -- structured result of query parsing
    normalize_query()   -- full normalization pipeline
    parse_query()       -- normalize + split into topic/keyword/options
"""

import re

from languages_data import LANGUAGE_ALIAS, rewrite_editor_section_name


# Single source of truth for the default topic shown when no query is given.
DEFAULT_TOPIC = ":firstpage"


class ParsedQuery:
    """Structured result of parsing a raw query string.

    Attributes:
        topic:           Normalized topic (e.g. "python/copy file").
        keyword:         Search keyword from ~ syntax, or None.
        search_options:  Search option flags (e.g. "ri"), or "".
        raw_query:       The original raw query string before normalization.
    """

    __slots__ = ("topic", "keyword", "search_options", "raw_query")

    def __init__(self, topic, keyword, search_options, raw_query):
        self.topic = topic
        self.keyword = keyword
        self.search_options = search_options
        self.raw_query = raw_query

    def __repr__(self):
        return (
            "ParsedQuery(topic=%r, keyword=%r, search_options=%r, raw_query=%r)"
            % (self.topic, self.keyword, self.search_options, self.raw_query)
        )

    def __eq__(self, other):
        if not isinstance(other, ParsedQuery):
            return NotImplemented
        return (
            self.topic == other.topic
            and self.keyword == other.keyword
            and self.search_options == other.search_options
            and self.raw_query == other.raw_query
        )


# ---------------------------------------------------------------------------
# Individual normalization steps
# ---------------------------------------------------------------------------


def sanitize_query(query):
    """Strip characters that could cause HTML/script injection."""
    return re.sub('[<>"]', "", query)


def add_section_name(query):
    """Convert multi-word queries into section/topic form.

    "python copy file" => "python/copy file"
    "python+file"      => "python/file"
    Queries that already contain "/" are returned unchanged.
    """
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
    return query


def rewrite_aliases(word):
    """Rewrite known query aliases."""
    if word == ":bash.completion":
        return ":bash_completion"
    return word


def rewrite_section_name(query):
    """Rewrite section (first path component) using language aliases
    and editor name mappings.

    "golang/tar"       => "go/tar"
    "emacs:go-mode/x"  => "go/x"
    """
    if "/" not in query:
        return query

    section_name, rest = query.split("/", 1)

    if ":" in section_name:
        section_name = rewrite_editor_section_name(section_name)
    section_name = LANGUAGE_ALIAS.get(section_name, section_name)

    return "%s/%s" % (section_name, rest)


# ---------------------------------------------------------------------------
# Composed pipeline
# ---------------------------------------------------------------------------


def normalize_query(raw_query):
    """Apply the full normalization pipeline to a raw query string.

    Steps (applied in order):
        1. sanitize        -- strip dangerous characters
        2. add_section_name -- convert space/+ separators to /
        3. rewrite_aliases  -- fix known aliases
        4. rewrite_section_name -- resolve language/editor names
    """
    query = sanitize_query(raw_query)
    query = add_section_name(query)
    query = rewrite_aliases(query)
    query = rewrite_section_name(query)
    return query


def _split_keyword(query):
    """Split a normalized query into (topic, keyword, search_options).

    Handles the ~keyword/search_options syntax:
        "btrfs~volume"       => ("btrfs", "volume", "")
        "python~socket/ri"   => ("python", "socket", "ir")
        "ls"                 => ("ls", None, "")
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


def parse_query(raw_query):
    """Parse a raw query string into a ParsedQuery.

    Applies the full normalization pipeline, then splits on ~
    to extract topic, keyword, and search options.
    """
    normalized = normalize_query(raw_query)
    topic, keyword, search_options = _split_keyword(normalized)
    return ParsedQuery(
        topic=topic,
        keyword=keyword,
        search_options=search_options,
        raw_query=raw_query,
    )
