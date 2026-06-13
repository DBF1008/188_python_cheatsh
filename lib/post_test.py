"""
Tests for the submission pipeline (lib/post.py).

Covers:
    * Explicit topic submission  (form field: key=topic, val=body)
    * Body-only submission        (form field: empty key, val=body)
    * Body-as-key submission      (form field: key=body, val=empty)
    * HTML / ANSI entry-point detection
    * Metadata sidecar creation and field completeness
    * Empty-content warning
    * Submissions report rendering (with and without data)
"""

import json
import os
import sys
import tempfile

import pytest

# Ensure lib/ is on sys.path so that `import post` works when
# running pytest from the repository root.
_LIB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from config import CONFIG  # noqa: E402
from post import (  # noqa: E402
    _save_cheatsheet,
    get_recent_submissions,
    get_submissions_report,
    parse_submission,
    process_post_request,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockHeaders:
    """Minimal dict-like headers object."""

    def __init__(self, ua="curl/7.68.0"):
        self._ua = ua

    def get(self, key, default=""):
        if key.lower() == "user-agent":
            return self._ua
        return default

    def getlist(self, key):
        return []


class _MockRequest:
    """Lightweight stand-in for a Flask/Werkzeug request."""

    def __init__(self, form=None, user_agent="curl/7.68.0",
                 remote_addr="127.0.0.1", path="/"):
        self.form = form or {}
        self.headers = _MockHeaders(user_agent)
        self.remote_addr = remote_addr
        self.path = path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def spool_dir(tmp_path):
    """Point CONFIG["path.spool"] at a fresh temp directory."""
    spool = str(tmp_path / "spool")
    os.makedirs(spool, exist_ok=True)
    original = CONFIG["path.spool"]
    CONFIG["path.spool"] = spool
    yield spool
    CONFIG["path.spool"] = original


# ---------------------------------------------------------------------------
# parse_submission() tests
# ---------------------------------------------------------------------------

class TestParseSubmission:

    def test_explicit_topic(self):
        """Normal form field: key=topic, val=body."""
        req = _MockRequest(form={"python/loops": "for i in range(10): pass"})
        parsed = parse_submission(req)

        assert parsed["topic"] == "python/loops"
        assert parsed["cheatsheet"] == "for i in range(10): pass"
        assert parsed["topic_from"] == "form"

    def test_body_only_empty_key(self):
        """Form field with empty key: val is the body, topic is None."""
        req = _MockRequest(form={"": "some cheatsheet body"})
        parsed = parse_submission(req)

        assert parsed["topic"] is None
        assert parsed["cheatsheet"] == "some cheatsheet body"
        assert parsed["topic_from"] == "default"

    def test_body_as_key_empty_value(self):
        """Form field with empty value: key is the body, topic is None."""
        req = _MockRequest(form={"the cheatsheet text": ""})
        parsed = parse_submission(req)

        assert parsed["topic"] is None
        assert parsed["cheatsheet"] == "the cheatsheet text"
        assert parsed["topic_from"] == "form_key"

    def test_source_format_ansi(self):
        """curl user-agent should be detected as ANSI/CLI entry."""
        req = _MockRequest(
            form={"git/rebase": "git rebase -i HEAD~3"},
            user_agent="curl/7.68.0",
        )
        parsed = parse_submission(req)
        assert parsed["source"] == "ansi"

    def test_source_format_html(self):
        """Browser user-agent should be detected as HTML entry."""
        req = _MockRequest(
            form={"git/rebase": "git rebase -i HEAD~3"},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        )
        parsed = parse_submission(req)
        assert parsed["source"] == "html"

    def test_source_format_various_cli_agents(self):
        """All known CLI user-agents should map to ANSI."""
        for ua in [
            "python-requests/2.25.1",
            "Wget/1.21",
            "HTTPie/3.2.1",
            "xh/0.18.0",
        ]:
            req = _MockRequest(form={"t": "body"}, user_agent=ua)
            assert parse_submission(req)["source"] == "ansi", (
                f"Expected ansi for user-agent: {ua}"
            )


# ---------------------------------------------------------------------------
# _save_cheatsheet() tests
# ---------------------------------------------------------------------------

class TestSaveCheatsheet:

    def test_creates_content_and_metadata(self, spool_dir):
        """Both the content file and the .meta.json sidecar are created."""
        content_file, meta_file, meta = _save_cheatsheet(
            "python/loops",
            "for i in range(10): pass",
            source="ansi",
            ip_addr="10.0.0.1",
        )

        assert os.path.isfile(content_file)
        assert os.path.isfile(meta_file)

        with open(content_file, "r", encoding="utf-8") as fh:
            assert fh.read() == "for i in range(10): pass"

    def test_metadata_fields_complete(self, spool_dir):
        """Metadata sidecar contains all required audit fields."""
        _content_file, meta_file, meta = _save_cheatsheet(
            "git/rebase",
            "git rebase -i HEAD~3",
            source="html",
            ip_addr="192.168.1.1",
            user_agent="Mozilla/5.0",
            request_path="/git/rebase",
        )

        # Verify returned dict
        required_keys = {
            "topic", "timestamp", "source_format", "ip_addr",
            "user_agent", "filename", "content_hash",
            "content_length", "is_content_empty", "request_path",
        }
        assert required_keys.issubset(meta.keys())

        # Verify persisted file matches
        with open(meta_file, "r", encoding="utf-8") as fh:
            persisted = json.load(fh)
        assert persisted == meta

        # Spot-check values
        assert meta["topic"] == "git/rebase"
        assert meta["source_format"] == "html"
        assert meta["ip_addr"] == "192.168.1.1"
        assert meta["content_length"] == len("git rebase -i HEAD~3")
        assert meta["is_content_empty"] is False
        assert meta["request_path"] == "/git/rebase"
        assert len(meta["content_hash"]) == 64  # SHA-256 hex

    def test_slash_in_topic_becomes_dot(self, spool_dir):
        """Slashes in topic names are replaced with dots in filenames."""
        content_file, _meta_file, _meta = _save_cheatsheet(
            "python/copy/file", "body",
        )
        basename = os.path.basename(content_file)
        assert basename.startswith("python.copy.file.")

    def test_empty_content_flagged(self, spool_dir):
        """is_content_empty is True for blank/whitespace-only content."""
        _, _, meta = _save_cheatsheet("t", "   \n  ")
        assert meta["is_content_empty"] is True

    def test_creates_spool_if_missing(self, tmp_path):
        """Spool directory is auto-created when it doesn't exist."""
        spool = str(tmp_path / "new_spool")
        assert not os.path.exists(spool)
        original = CONFIG["path.spool"]
        CONFIG["path.spool"] = spool
        try:
            _save_cheatsheet("t", "body")
            assert os.path.isdir(spool)
        finally:
            CONFIG["path.spool"] = original


# ---------------------------------------------------------------------------
# process_post_request() tests  (end-to-end through the pipeline)
# ---------------------------------------------------------------------------

class TestProcessPostRequest:

    def test_explicit_topic_submission(self, spool_dir):
        """POST with key=topic, val=body uses the form key as topic."""
        req = _MockRequest(
            form={"python/loops": "for i in range(10): pass"},
            user_agent="curl/7.68.0",
        )
        result = process_post_request(req)
        assert result == "OK\n"

        submissions = get_recent_submissions()
        assert len(submissions) == 1
        assert submissions[0]["topic"] == "python/loops"
        assert submissions[0]["source_format"] == "ansi"

    def test_body_only_uses_url_topic(self, spool_dir):
        """POST with empty key uses the URL topic when available."""
        req = _MockRequest(
            form={"": "body content here"},
            user_agent="curl/7.68.0",
        )
        result = process_post_request(req, topic="vim/macros")
        assert result == "OK\n"

        submissions = get_recent_submissions()
        assert len(submissions) == 1
        assert submissions[0]["topic"] == "vim/macros"

    def test_body_only_no_url_topic_defaults_unnamed(self, spool_dir):
        """POST with empty key and no URL topic defaults to UNNAMED."""
        req = _MockRequest(
            form={"": "body content here"},
            user_agent="curl/7.68.0",
        )
        result = process_post_request(req)
        assert result == "OK\n"

        submissions = get_recent_submissions()
        assert submissions[0]["topic"] == "UNNAMED"

    def test_body_as_key_submission(self, spool_dir):
        """POST with key=body, val=empty uses the key as body."""
        req = _MockRequest(
            form={"ls -la --color": ""},
            user_agent="curl/7.68.0",
        )
        result = process_post_request(req, topic="bash/ls")
        assert result == "OK\n"

        submissions = get_recent_submissions()
        assert submissions[0]["topic"] == "bash/ls"

    def test_html_entry_point(self, spool_dir):
        """Browser user-agent is recorded as HTML entry."""
        req = _MockRequest(
            form={"git/status": "git status -s"},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) Chrome/91.0",
            remote_addr="10.0.0.5",
            path="/git/status",
        )
        result = process_post_request(req)
        assert result == "OK\n"

        submissions = get_recent_submissions()
        assert len(submissions) == 1
        sub = submissions[0]
        assert sub["source_format"] == "html"
        assert sub["ip_addr"] == "10.0.0.5"
        assert sub["topic"] == "git/status"

    def test_ansi_entry_point(self, spool_dir):
        """curl user-agent is recorded as ANSI entry."""
        req = _MockRequest(
            form={"docker/ps": "docker ps -a"},
            user_agent="curl/7.68.0",
            remote_addr="192.168.0.1",
        )
        result = process_post_request(req)
        assert result == "OK\n"

        submissions = get_recent_submissions()
        sub = submissions[0]
        assert sub["source_format"] == "ansi"
        assert sub["ip_addr"] == "192.168.0.1"

    def test_empty_submission_returns_warning(self, spool_dir):
        """Empty cheatsheet body triggers a warning return value."""
        req = _MockRequest(
            form={"": "  "},
            user_agent="curl/7.68.0",
        )
        result = process_post_request(req, topic="python/empty")
        assert "WARN" in result
        assert "empty" in result.lower()

        # Content is still saved for audit purposes
        submissions = get_recent_submissions()
        assert len(submissions) == 1
        assert submissions[0]["is_content_empty"] is True
        assert submissions[0]["topic"] == "python/empty"

    def test_ip_addr_from_request_fallback(self, spool_dir):
        """When ip_addr is not passed explicitly, it comes from the request."""
        req = _MockRequest(
            form={"t": "body"},
            remote_addr="172.16.0.99",
        )
        process_post_request(req)
        submissions = get_recent_submissions()
        assert submissions[0]["ip_addr"] == "172.16.0.99"


# ---------------------------------------------------------------------------
# get_submissions_report() / get_recent_submissions() tests
# ---------------------------------------------------------------------------

class TestSubmissionsReport:

    def test_report_empty_spool(self, spool_dir):
        """Report for an empty spool says 'no submissions'."""
        report = get_submissions_report()
        assert "No submissions yet." in report

    def test_report_with_submissions(self, spool_dir):
        """Report includes topic, format, and timestamp for each entry."""
        req1 = _MockRequest(
            form={"python/loops": "for i in range(10): pass"},
            user_agent="curl/7.68.0",
        )
        req2 = _MockRequest(
            form={"git/rebase": "git rebase -i HEAD~3"},
            user_agent="Mozilla/5.0 Chrome/91.0",
        )
        process_post_request(req1)
        process_post_request(req2)

        report = get_submissions_report()
        assert "Recent Submissions" in report
        assert "python/loops" in report
        assert "git/rebase" in report
        assert "ANSI/CLI" in report
        assert "HTML/Browser" in report
        assert "Total shown: 2" in report

    def test_report_flags_empty_content(self, spool_dir):
        """Empty submissions are tagged with [EMPTY] in the report."""
        req = _MockRequest(
            form={"python/empty": "  "},
            user_agent="curl/7.68.0",
        )
        process_post_request(req)

        report = get_submissions_report()
        assert "[EMPTY]" in report

    def test_recent_submissions_limit(self, spool_dir):
        """get_recent_submissions respects the limit parameter."""
        for i in range(5):
            req = _MockRequest(form={"topic%d" % i: "body%d" % i})
            process_post_request(req)

        subs = get_recent_submissions(limit=3)
        assert len(subs) == 3

    def test_recent_submissions_newest_first(self, spool_dir):
        """Submissions are returned newest-first."""
        req1 = _MockRequest(form={"first": "body1"})
        req2 = _MockRequest(form={"second": "body2"})
        process_post_request(req1)
        process_post_request(req2)

        subs = get_recent_submissions()
        assert subs[0]["topic"] == "second"
        assert subs[1]["topic"] == "first"
