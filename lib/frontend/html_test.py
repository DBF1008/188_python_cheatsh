"""Regression tests for the GitHub edit link path restoration.

The cheat.sheets repository uses an underscore prefix on every directory
component (e.g. ``_go/_strings/TrimSuffix``), while user-facing queries
drop those underscores (``go/strings/TrimSuffix``).  The edit link must
restore the real repository path.

Covers:
    * root page          (e.g. ``ls``)
    * single-level dir   (e.g. ``go/fmt``)
    * multi-level dir    (e.g. ``go/strings/TrimSuffix``)
"""

import sys
import types
import os

# Ensure lib/ is on sys.path so that application modules are importable.
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

# ---------------------------------------------------------------------------
# Stub out heavy optional dependencies (polyglot/icu) so that the full
# adapter package can be imported in CI environments that lack them.
# ---------------------------------------------------------------------------
for _mod_name in (
    "icu",
    "polyglot",
    "polyglot.detect",
    "polyglot.detect.base",
    "polyglot.detect.language",
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)

# Provide minimal stubs so that adapter.question can import.
_polyglot_detect = sys.modules["polyglot.detect"]
if not hasattr(_polyglot_detect, "Detector"):

    class _FakeDetector:  # pragma: no cover
        def __init__(self, *a, **kw):
            self.language = types.SimpleNamespace(code="en")
            self.languages = []

    _polyglot_detect.Detector = _FakeDetector

_polyglot_detect_base = sys.modules["polyglot.detect.base"]
if not hasattr(_polyglot_detect_base, "UnknownLanguage"):
    _polyglot_detect_base.UnknownLanguage = Exception

from adapter.cheat_sheets import _sanitize_dirnames  # noqa: E402
from frontend.html import _build_edit_link  # noqa: E402


_BASE = "https://github.com/chubin/cheat.sheets/edit/master/sheets/"


# --- _sanitize_dirnames (restore=True) -----------------------------------


class TestSanitizeDirnamesRestore:
    """Unit tests for the low-level path restoration helper."""

    def test_root_page_unchanged(self):
        """A plain sheet name (no directory) must not be modified."""
        assert _sanitize_dirnames("ls", restore=True) == "ls"

    def test_single_level_dir(self):
        """One directory level: only that directory gets a '_' prefix."""
        assert _sanitize_dirnames("go/fmt", restore=True) == "_go/fmt"

    def test_multi_level_dir(self):
        """Multiple directory levels: EACH directory gets a '_' prefix."""
        assert (
            _sanitize_dirnames("go/strings/TrimSuffix", restore=True)
            == "_go/_strings/TrimSuffix"
        )

    def test_three_level_dir(self):
        """Three directory levels: all three get '_' prefixes."""
        assert (
            _sanitize_dirnames("a/b/c/d", restore=True) == "_a/_b/_c/d"
        )


# --- _sanitize_dirnames (restore=False) ----------------------------------


class TestSanitizeDirnamesStrip:
    """Verify the forward direction (repo path -> query) still works."""

    def test_root_page(self):
        assert _sanitize_dirnames("ls", restore=False) == "ls"

    def test_single_level(self):
        assert _sanitize_dirnames("_go/fmt", restore=False) == "go/fmt"

    def test_multi_level(self):
        assert (
            _sanitize_dirnames("_go/_strings/TrimSuffix", restore=False)
            == "go/strings/TrimSuffix"
        )


# --- _build_edit_link (end-to-end) ---------------------------------------


class TestBuildEditLink:
    """Verify the full GitHub edit URL for different query shapes."""

    def test_root_page(self):
        assert _build_edit_link("ls") == _BASE + "ls"

    def test_single_level_dir(self):
        assert _build_edit_link("go/fmt") == _BASE + "_go/fmt"

    def test_multi_level_dir(self):
        assert (
            _build_edit_link("go/strings/TrimSuffix")
            == _BASE + "_go/_strings/TrimSuffix"
        )

    def test_php_strtotime(self):
        """Another single-level example to guard against regressions."""
        assert _build_edit_link("php/strtotime") == _BASE + "_php/strtotime"

    def test_deep_nesting(self):
        """Four-level deep query should prefix every directory."""
        assert (
            _build_edit_link("rust/book/ownership/borrowing")
            == _BASE + "_rust/_book/_ownership/borrowing"
        )
