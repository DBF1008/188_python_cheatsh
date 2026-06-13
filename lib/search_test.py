"""
Regression tests for ``search.match()``.

The word-boundary search mode (the ``b`` option) used to splice the *raw*
keyword into the regular expression.  Keywords containing regex metacharacters
such as ``c++``, ``foo.bar`` or ``[test]`` were therefore either rejected with
``re.error`` or matched the wrong text (e.g. ``c++`` matching a lone ``c``).
These tests pin down the expected behaviour and also cover case sensitivity
(the ``i`` option) and several keywords joined with ``~``.
"""

from search import match


def _check(cases):
    """Assert ``match(paragraph, keyword, options)`` for every case."""
    for paragraph, keyword, options, expected in cases:
        got = match(paragraph, keyword, options=options)
        assert got == expected, (
            "match(%r, keyword=%r, options=%r) == %r, expected %r"
            % (paragraph, keyword, options, got, expected)
        )


def test_plain_keyword_substring():
    # Without the boundary option a keyword may match as a substring.
    _check([
        ("connect via ssh today", "ssh", "", True),
        ("nothing relevant here", "ssh", "", False),
        ("use ssh-keygen now", "ssh", "", True),
        ("concatenate the list", "cat", "", True),
    ])


def test_case_insensitive():
    _check([
        ("Generate SSH passphrase", "ssh", "", False),
        ("Generate SSH passphrase", "ssh", "i", True),
        ("Generate SSH passphrase", "ssh", "bi", True),
        ("Generate SSH passphrase", "SSH", "", True),
    ])


def test_word_boundaries_whole_word():
    _check([
        ("ssh-keygen -t rsa", "ssh", "b", True),      # whole token before '-'
        ("a cat sleeps", "cat", "b", True),
        ("concatenate strings", "cat", "b", False),   # inner substring rejected
        ("category theory", "cat", "b", False),       # prefix substring rejected
    ])


def test_special_characters_with_boundaries():
    # Previously these crashed (re.error) or matched the wrong text.
    _check([
        ("install the c++ compiler", "c++", "b", True),
        ("plain c programs", "c++", "b", False),          # must not match lone 'c'
        ("edit foo.bar in place", "foo.bar", "b", True),
        ("edit fooXbar in place", "foo.bar", "b", False),  # '.' stays literal
        ("the [test] section", "[test]", "b", True),
        ("only t and e here", "[test]", "b", False),       # not a character class
    ])


def test_special_characters_without_boundaries():
    _check([
        ("install the c++ compiler", "c++", "", True),
        ("edit fooXbar in place", "foo.bar", "", False),
        ("the [test] section", "[test]", "", True),
        ("only t and e here", "[test]", "", False),
    ])


def test_multiple_keywords_with_tilde():
    _check([
        # all keywords must be present (AND semantics)
        ("ssh with passphrase", "ssh~passphrase", "", True),
        ("ssh without secret", "ssh~passphrase", "", False),
        # options apply to every keyword: boundaries + special chars
        ("use c++ and make", "c++~make", "b", True),
        ("use c++ only", "c++~make", "b", False),
        # empty segments produced by a leading '~' are ignored
        ("just passphrase here", "~passphrase", "", True),
    ])


def test_no_keyword_matches_everything():
    assert match("anything at all", None) is True
