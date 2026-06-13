"""
conftest.py for cheat.sh tests.

Mocks unavailable dependencies (e.g. icu/polyglot) so that adapter
modules can be imported in the test environment without the full
dependency set installed.
"""

import sys
from unittest.mock import MagicMock

# Mock icu (required by polyglot.detect, which is imported by adapter.question)
if "icu" not in sys.modules:
    _icu_mock = MagicMock()
    _icu_mock.Locale = MagicMock()
    sys.modules["icu"] = _icu_mock

# Mock polyglot.detect if not already available
if "polyglot" not in sys.modules:
    _polyglot_mock = MagicMock()
    _polyglot_mock.detect = MagicMock()
    _polyglot_mock.detect.Detector = MagicMock()
    _polyglot_mock.detect.base = MagicMock()
    _polyglot_mock.detect.base.UnknownLanguage = type("UnknownLanguage", (Exception,), {})
    sys.modules["polyglot"] = _polyglot_mock
    sys.modules["polyglot.detect"] = _polyglot_mock.detect
    sys.modules["polyglot.detect.base"] = _polyglot_mock.detect.base
