"""
Unit tests for the cheat sheet submission pipeline (`post.py`).

These cover the two documented submission entries -- an explicit topic
posted as a form field, and a body posted against a URL topic -- as well as
the metadata that gets spooled for manual review and the `:submissions`
preview rendering.
"""

import json
import os

import post


class _Form:
    """Minimal stand-in for Flask's `request.form` (only `.items()`)."""

    def __init__(self, pairs):
        self._pairs = list(pairs)

    def items(self):
        return list(self._pairs)


class _Req:
    def __init__(self, pairs):
        self.form = _Form(pairs)


def _use_spool(tmp_path):
    spool = str(tmp_path)
    post.CONFIG["path.spool"] = spool
    return spool


def _metadata(spool):
    metas = []
    for name in sorted(os.listdir(spool)):
        if name.endswith(".json"):
            with open(os.path.join(spool, name)) as handle:
                metas.append(json.load(handle))
    return metas


def _content(spool, filename):
    with open(os.path.join(spool, filename)) as handle:
        return handle.read()


def test_explicit_topic_submission(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(
        _Req([("python/hello", 'print("hi")')]), None, html_needed=True
    )

    metas = _metadata(spool)
    assert len(metas) == 1
    meta = metas[0]
    assert meta["topic"] == "python/hello"
    assert meta["topic_source"] == "form"
    assert meta["entry"] == "html"
    assert meta["empty"] is False
    assert meta["bytes"] == len('print("hi")'.encode("utf-8"))
    # the "/" in the topic becomes "." in the spooled file name
    assert meta["filename"].startswith("python.hello.")
    assert _content(spool, meta["filename"]) == 'print("hi")'


def test_body_only_submission_uses_url_topic(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(
        _Req([("some body content", "")]), "golang/foo", html_needed=False
    )

    meta = _metadata(spool)[0]
    assert meta["topic"] == "golang/foo"
    assert meta["topic_source"] == "url"
    assert meta["entry"] == "ansi"
    assert meta["empty"] is False
    assert _content(spool, meta["filename"]) == "some body content"


def test_empty_field_name_submission_uses_url_topic(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(_Req([("", "the body")]), "rust", html_needed=False)

    meta = _metadata(spool)[0]
    assert meta["topic"] == "rust"
    assert meta["topic_source"] == "url"
    assert _content(spool, meta["filename"]) == "the body"


def test_unnamed_topic_when_no_url_topic(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(_Req([("body text", "")]), None, html_needed=False)

    meta = _metadata(spool)[0]
    assert meta["topic"] == "UNNAMED"
    assert meta["topic_source"] == "unnamed"


def test_empty_body_is_flagged(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(_Req([("", "")]), "emptytopic", html_needed=True)

    meta = _metadata(spool)[0]
    assert meta["empty"] is True
    assert meta["bytes"] == 0
    assert _content(spool, meta["filename"]) == ""


def test_entry_records_html_and_ansi(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(_Req([("htmltopic", "x")]), None, html_needed=True)
    post.process_post_request(_Req([("ansitopic", "y")]), None, html_needed=False)

    entries = {meta["topic"]: meta["entry"] for meta in _metadata(spool)}
    assert entries == {"htmltopic": "html", "ansitopic": "ansi"}


def test_multiple_fields_are_each_spooled(tmp_path):
    spool = _use_spool(tmp_path)

    post.process_post_request(
        _Req([("alpha", "1"), ("beta", "2")]), None, html_needed=True
    )

    metas = _metadata(spool)
    assert len(metas) == 2
    assert {meta["topic"] for meta in metas} == {"alpha", "beta"}
    assert all(meta["topic_source"] == "form" for meta in metas)


def test_recent_submissions_summary(tmp_path):
    _use_spool(tmp_path)

    post.process_post_request(_Req([("git/clone", "git clone url")]), None, True)
    post.process_post_request(_Req([("body", "")]), "tar/extract", False)

    summary = post.recent_submissions()
    assert "TOPIC" in summary and "SOURCE" in summary and "ENTRY" in summary
    assert "git/clone" in summary
    assert "tar/extract" in summary
    assert "form" in summary and "url" in summary


def test_recent_submissions_empty_spool(tmp_path):
    # point at a directory that does not exist yet
    post.CONFIG["path.spool"] = str(tmp_path / "does-not-exist")
    assert post.recent_submissions() == "No submissions have been spooled yet.\n"
