"""
POST requests processing.

This module implements the cheat sheet submission pipeline. A submission
goes through three stages:

    1. parsing -- the incoming POST form is normalized into submission
       records, resolving the topic and where both the topic and the
       content came from (an explicit form field, the URL path, or
       neither);
    2. spooling -- each submission is written to the spool directory
       together with a structured metadata sidecar describing it, so that
       it can be audited later;
    3. review -- `recent_submissions()` renders a short summary of the most
       recently spooled submissions for manual review (see the internal
       `:submissions` page).

Configuration parameters:

    path.spool
"""

import json
import os
import random
import string
import time

from config import CONFIG

# length of the random suffix appended to spooled cheat sheet file names
_NONCE_LENGTH = 9

# suffix of the metadata sidecar accompanying each spooled cheat sheet
_METADATA_SUFFIX = ".json"

# how many submissions `recent_submissions()` shows by default
_RECENT_LIMIT = 20

# topic used when a submission carries neither a form-field nor a URL topic
_UNNAMED_TOPIC = "UNNAMED"


def _spool_dir():
    return CONFIG["path.spool"]


def _parse_submission(form, url_topic, html_needed):
    """
    Normalize a POST `form` into a list of submission records.

    `form` is a mapping (Flask `request.form`) of the submitted fields,
    `url_topic` is the topic taken from the request path (may be None), and
    `html_needed` tells whether the request arrived through the HTML entry
    (a browser) or the ANSI entry (curl and friends).

    Each record is a dict with the keys:

        topic         resolved topic name the sheet will be filed under
        content       the cheat sheet body
        topic_source  where the topic came from: "form", "url" or "unnamed"
        entry         request entry the submission came through: "html"/"ansi"
        empty         True if the body is blank
    """

    entry = "html" if html_needed else "ansi"

    def _from_url():
        if url_topic is None:
            return _UNNAMED_TOPIC, "unnamed"
        return url_topic, "url"

    records = []
    for key, val in form.items():
        if key == "":
            # body posted with an empty field name -> topic comes from URL
            topic, topic_source = _from_url()
            content = val
        elif val == "":
            # body posted as the field name (e.g. `--data-binary @file`)
            # -> topic comes from URL
            topic, topic_source = _from_url()
            content = key
        else:
            # explicit `field=value` submission -> the field name is the topic
            topic, topic_source = key, "form"
            content = val

        records.append(
            {
                "topic": topic,
                "content": content,
                "topic_source": topic_source,
                "entry": entry,
                "empty": content.strip() == "",
            }
        )

    return records


def _save_cheatsheet(topic, content):
    """
    Save cheat sheet `content` for `topic` in the spool directory.

    Return the base name of the file that was written.
    """

    nonce = "".join(
        random.choice(string.ascii_uppercase + string.digits)
        for _ in range(_NONCE_LENGTH)
    )
    filename = topic.replace("/", ".") + "." + nonce

    spool_dir = _spool_dir()
    os.makedirs(spool_dir, exist_ok=True)
    with open(os.path.join(spool_dir, filename), "w") as output:
        output.write(content)

    return filename


def _save_metadata(record, filename):
    """
    Save structured metadata describing a spooled submission next to its
    cheat sheet file, as `<filename>.json`.

    Return the metadata dict that was written.
    """

    metadata = {
        "topic": record["topic"],
        "topic_source": record["topic_source"],
        "entry": record["entry"],
        "empty": record["empty"],
        "bytes": len(record["content"].encode("utf-8")),
        "filename": filename,
        "timestamp": time.time(),
    }

    path = os.path.join(_spool_dir(), filename + _METADATA_SUFFIX)
    with open(path, "w") as output:
        json.dump(metadata, output, ensure_ascii=False, sort_keys=True)

    return metadata


def process_post_request(req, topic, html_needed):
    """
    Process POST request `req` submitting one or more cheat sheets.

    `topic` is the topic taken from the request URL (may be None) and
    `html_needed` indicates the request entry (HTML browser vs ANSI client).
    Each submitted field is spooled together with its metadata sidecar.
    """

    for record in _parse_submission(req.form, topic, html_needed):
        filename = _save_cheatsheet(record["topic"], record["content"])
        _save_metadata(record, filename)


def _load_submissions(limit):
    """
    Return metadata for the `limit` most recently spooled submissions,
    newest first. Missing spool directory and unreadable or malformed
    metadata files are skipped rather than raising.
    """

    spool_dir = _spool_dir()
    try:
        names = [
            name
            for name in os.listdir(spool_dir)
            if name.endswith(_METADATA_SUFFIX)
        ]
    except FileNotFoundError:
        return []

    names.sort(
        key=lambda name: os.path.getmtime(os.path.join(spool_dir, name)),
        reverse=True,
    )

    submissions = []
    for name in names[:limit]:
        try:
            with open(os.path.join(spool_dir, name)) as handle:
                submissions.append(json.load(handle))
        except (ValueError, OSError):
            continue

    return submissions


def recent_submissions(limit=_RECENT_LIMIT):
    """
    Render a short, human readable summary of the most recent submissions
    found in the spool directory, newest first. Used by the internal
    `:submissions` page for manual review.
    """

    submissions = _load_submissions(limit)
    if not submissions:
        return "No submissions have been spooled yet.\n"

    header = ("DATE", "TOPIC", "SOURCE", "ENTRY", "EMPTY", "BYTES", "FILE")
    rows = [header]
    for sub in submissions:
        when = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(sub.get("timestamp", 0))
        )
        rows.append(
            (
                when,
                str(sub.get("topic", "")),
                str(sub.get("topic_source", "")),
                str(sub.get("entry", "")),
                "yes" if sub.get("empty") else "no",
                str(sub.get("bytes", "")),
                str(sub.get("filename", "")),
            )
        )

    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join(lines) + "\n"
