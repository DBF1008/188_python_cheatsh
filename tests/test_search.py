"""
Regression tests for search.match() — keyword search with word boundaries.

Covers:
  * Case-sensitive / case-insensitive matching
  * Word-boundary mode with plain keywords
  * Regex metacharacters in keywords  (c++, foo.bar, [test], etc.)
  * Multi-keyword ~ joining
  * Edge cases (None keyword, empty keyword segments)
"""

import os
import sys
import types
import unittest

# ---- bootstrap: stub heavy deps so we can import lib.search standalone ----
# search.py does:  from config import CONFIG
#                  from routing import get_answers, get_topics_list
# We never call find_answers_by_keyword here, so stubs are enough.

_test_dir = os.path.dirname(os.path.abspath(__file__))
_lib_dir = os.path.join(_test_dir, "..", "lib")

_fake_config = types.ModuleType("config")
_fake_config.CONFIG = {"search.limit": 20}

_fake_routing = types.ModuleType("routing")
_fake_routing.get_answers = lambda *a, **kw: []
_fake_routing.get_topics_list = lambda *a, **kw: []

sys.modules.setdefault("config", _fake_config)
sys.modules.setdefault("routing", _fake_routing)

if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

import search  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match(text, keyword, options_str=""):
    """Convenience wrapper around search.match using an options string."""
    return search.match(text, keyword, options=options_str)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestMatchBasic(unittest.TestCase):
    """Plain keyword matching (no word boundaries, no case flag)."""

    def test_simple_match(self):
        self.assertTrue(_match("hello world", "hello"))

    def test_simple_no_match(self):
        self.assertFalse(_match("hello world", "xyz"))

    def test_case_sensitive_by_default(self):
        self.assertFalse(_match("Hello World", "hello"))

    def test_substring_match(self):
        # Without word boundaries, substring should match
        self.assertTrue(_match("abcdefgh", "cde"))

    def test_none_keyword_always_matches(self):
        self.assertTrue(_match("anything", None))

    def test_empty_keyword_segment(self):
        # keyword="" is falsy, the loop skips it → returns True
        self.assertTrue(_match("anything", ""))


class TestMatchCaseInsensitive(unittest.TestCase):
    """Case-insensitive matching (option 'i')."""

    def test_insensitive_match(self):
        self.assertTrue(_match("Hello World", "hello", "i"))

    def test_insensitive_mixed_case(self):
        self.assertTrue(_match("HeLLo WoRLd", "hello world", "i"))

    def test_insensitive_no_match(self):
        self.assertFalse(_match("Hello World", "xyz", "i"))


class TestMatchWordBoundaries(unittest.TestCase):
    """Word-boundary matching (option 'b')."""

    def test_whole_word_match(self):
        self.assertTrue(_match("the quick brown fox", "quick", "b"))

    def test_substring_rejected(self):
        # "quicksort" contains "quick" but it's not a whole word
        self.assertFalse(_match("quicksort is fast", "quick", "b"))

    def test_word_at_start(self):
        self.assertTrue(_match("hello world", "hello", "b"))

    def test_word_at_end(self):
        self.assertTrue(_match("hello world", "world", "b"))

    def test_single_char_word(self):
        self.assertTrue(_match("a b c", "b", "b"))

    def test_single_char_rejects_substring(self):
        self.assertFalse(_match("abc", "b", "b"))


class TestMatchWordBoundariesCaseInsensitive(unittest.TestCase):
    """Combined 'b' + 'i' options."""

    def test_boundary_insensitive_match(self):
        self.assertTrue(_match("Hello World", "hello", "bi"))

    def test_boundary_insensitive_reject_substring(self):
        self.assertFalse(_match("Helloworld", "hello", "bi"))


class TestMatchRegexMetacharacters(unittest.TestCase):
    """Keywords containing regex metacharacters must be treated as literals."""

    # -- without word boundaries --

    def test_plus_no_boundary(self):
        self.assertTrue(_match("use c++ here", "c++"))

    def test_plus_reject_regex_interpretation(self):
        # "c+" as regex would mean "one or more c"; must not match "ccc"
        self.assertFalse(_match("ccc", "c+"))

    def test_dot_no_boundary(self):
        self.assertTrue(_match("open foo.bar", "foo.bar"))

    def test_dot_not_wildcard(self):
        # "foo.bar" as regex would match "fooXbar"; escaped it must not
        self.assertFalse(_match("fooXbar", "foo.bar"))

    def test_brackets_no_boundary(self):
        self.assertTrue(_match("array [test] here", "[test]"))

    def test_brackets_not_char_class(self):
        # "[test]" as regex char class would match single 't'; must not
        self.assertFalse(_match("just a t here", "[test]"))

    def test_parentheses(self):
        self.assertTrue(_match("call foo(bar)", "foo(bar)"))

    def test_pipe_literal(self):
        self.assertTrue(_match("use a|b operator", "a|b"))

    def test_pipe_not_alternation(self):
        # "a|b" as regex would match just "a"; must not
        self.assertFalse(_match("just a here", "a|b"))

    def test_backslash_literal(self):
        self.assertTrue(_match(r"path is c:\dir", r"c:\dir"))

    def test_dollar_literal(self):
        self.assertTrue(_match("price is $100", "$100"))

    def test_caret_literal(self):
        self.assertTrue(_match("2^8 is 256", "2^8"))

    def test_question_literal(self):
        self.assertTrue(_match("what?", "what?"))

    def test_star_literal(self):
        self.assertTrue(_match("import * from", "import * from"))

    # -- with word boundaries --

    def test_plus_with_boundary(self):
        """c++ should match as a whole token."""
        self.assertTrue(_match("I use c++ daily", "c++", "b"))

    def test_plus_with_boundary_rejects_embedded(self):
        """c++ inside a longer token should not match with boundaries."""
        self.assertFalse(_match("xc++y", "c++", "b"))

    def test_plus_with_boundary_at_string_start(self):
        self.assertTrue(_match("c++ is great", "c++", "b"))

    def test_plus_with_boundary_at_string_end(self):
        self.assertTrue(_match("language is c++", "c++", "b"))

    def test_dot_with_boundary(self):
        """foo.bar should match as a whole token."""
        self.assertTrue(_match("open foo.bar now", "foo.bar", "b"))

    def test_dot_with_boundary_rejects_prefix(self):
        self.assertFalse(_match("xfoo.bar", "foo.bar", "b"))

    def test_dot_with_boundary_rejects_suffix(self):
        self.assertFalse(_match("foo.barx", "foo.bar", "b"))

    def test_brackets_with_boundary(self):
        """[test] surrounded by spaces should match."""
        self.assertTrue(_match("array [test] here", "[test]", "b"))

    def test_parentheses_with_boundary(self):
        self.assertTrue(_match("call foo(bar) now", "foo(bar)", "b"))

    def test_special_chars_with_boundary_no_re_error(self):
        """Ensure no re.error is raised for any metachar in boundary mode."""
        metachars = ["c++", "foo.bar", "[test]", "a(b)", "x|y",
                      "$100", "2^8", "a?b", "a*b", "a+b", "a{2}",
                      "foo\\bar"]
        for kw in metachars:
            # Should not raise re.error
            try:
                search.match("some text " + kw + " more text", kw, options="b")
            except Exception as exc:
                self.fail(f"re.error raised for keyword {kw!r}: {exc}")

    def test_boundary_insensitive_metachar(self):
        """Combined bi options with metachar keyword."""
        self.assertTrue(_match("USE C++ HERE", "c++", "bi"))


class TestMultiKeyword(unittest.TestCase):
    """Multiple keywords joined with ~."""

    def test_all_match(self):
        self.assertTrue(_match("hello beautiful world", "hello~world"))

    def test_one_missing(self):
        self.assertFalse(_match("hello world", "hello~xyz"))

    def test_multi_with_boundaries(self):
        self.assertTrue(_match("the quick brown fox", "quick~fox", "b"))

    def test_multi_boundary_rejects_substring(self):
        self.assertFalse(_match("quicksort and foxtrot", "quick~fox", "b"))

    def test_multi_with_metachar(self):
        self.assertTrue(_match("c++ and foo.bar", "c++~foo.bar"))

    def test_multi_boundary_with_metachar(self):
        self.assertTrue(_match("c++ and foo.bar", "c++~foo.bar", "b"))

    def test_empty_segments_ignored(self):
        # leading/trailing ~ produces empty segments; they are skipped
        self.assertTrue(_match("hello world", "~hello~"))


class TestParseOptions(unittest.TestCase):
    """Verify _parse_options helper."""

    def test_empty_string(self):
        opts = search._parse_options("")
        self.assertFalse(opts["insensitive"])
        self.assertFalse(opts["word_boundaries"])
        self.assertFalse(opts["recursive"])

    def test_all_flags(self):
        opts = search._parse_options("bir")
        self.assertTrue(opts["insensitive"])
        self.assertTrue(opts["word_boundaries"])
        self.assertTrue(opts["recursive"])

    def test_none_returns_empty(self):
        self.assertEqual(search._parse_options(None), {})


if __name__ == "__main__":
    unittest.main()
