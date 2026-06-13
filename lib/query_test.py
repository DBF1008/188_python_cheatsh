"""
Regression tests for the shared query parsing/normalization pipeline.

These cover the behaviors the web and standalone entry points rely on:
plain topic lookup, search queries (with and without options), and the
empty-input default page, plus the sanitize/alias/section rewrites.
All cases are offline (only `query` -> `languages_data` is imported).
"""

from query import DEFAULT_TOPIC, ParsedQuery, default_topic


def _parsed(query):
    return ParsedQuery.from_query(query)


def test_default_topic():
    assert DEFAULT_TOPIC == ":firstpage"
    assert default_topic(None) == DEFAULT_TOPIC
    assert default_topic("") == DEFAULT_TOPIC
    assert default_topic("python") == "python"


def test_plain_topic():
    parsed = _parsed("python")
    assert parsed.query == "python"
    assert parsed.topic == "python"
    assert parsed.keyword is None
    assert parsed.search_options == ""
    assert parsed.is_search is False


def test_topic_with_section_split():
    # first space becomes the section separator
    parsed = _parsed("python list comprehension")
    assert parsed.topic == "python/list comprehension"
    assert parsed.keyword is None
    assert parsed.is_search is False


def test_search():
    parsed = _parsed("btrfs~volume")
    assert parsed.topic == "btrfs"
    assert parsed.keyword == "volume"
    assert parsed.search_options == ""
    assert parsed.is_search is True


def test_search_with_options():
    # trailing /options after the keyword are pulled out as search options
    parsed = _parsed("g/foo~bar/i")
    assert parsed.topic == "g/foo"
    assert parsed.keyword == "bar"
    assert parsed.search_options == "i"
    assert parsed.is_search is True


def test_empty_defaults_to_firstpage():
    parsed = _parsed("")
    assert parsed.query == ":firstpage"
    assert parsed.topic == ":firstpage"
    assert parsed.keyword is None
    assert parsed.is_search is False


def test_alias_rewrite():
    assert _parsed(":bash.completion").topic == ":bash_completion"


def test_language_alias_section():
    assert _parsed("c++/foo").topic == "cpp/foo"


def test_editor_section_rewrite():
    assert _parsed("emacs:go-mode/foo").topic == "go/foo"


def test_sanitize_removes_unsafe_chars():
    assert _parsed("py<th>on").topic == "python"
