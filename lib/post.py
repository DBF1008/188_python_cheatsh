"""
POST requests processing.
Submission pipeline for new cheat sheets.

Provides:
    process_post_request(req, topic, ip_addr, user_agent)
    get_submissions_report(limit)

Configuration parameters:

    path.spool
"""

import hashlib
import json
import os
import random
import string
from datetime import datetime, timezone

from config import CONFIG


def _generate_nonce(length=9):
    """Generate a random alphanumeric nonce."""
    return "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(length)
    )


def _content_hash(text):
    """Return SHA-256 hex digest of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_submission(req):
    """
    Uniformly parse topic, cheatsheet content, and entry format
    from a POST request.

    Returns
    -------
    dict with keys:
        topic      : str   - resolved topic name (never None)
        cheatsheet : str   - raw cheatsheet body
        source     : str   - "html" | "ansi"  (entry point)
        topic_from : str   - "url" | "form" | "form_key" | "default"
    """
    user_agent = req.headers.get("User-Agent", "").lower()
    is_html = all(
        agent not in user_agent
        for agent in [
            "curl", "httpie", "lwp-request", "wget",
            "python-requests", "openbsd ftp", "powershell",
            "fetch", "aiohttp", "xh",
        ]
    )
    source = "html" if is_html else "ansi"

    topic = None
    cheatsheet = ""
    topic_from = "default"

    for key, val in req.form.items():
        if key == "":
            # Form field with empty key: value is the cheatsheet body
            cheatsheet = val
            topic_from = "default"
        elif val == "":
            # Form field with empty value: key is the cheatsheet body
            cheatsheet = key
            topic_from = "form_key"
        else:
            # Normal form field: key=topic, value=cheatsheet
            topic = key
            cheatsheet = val
            topic_from = "form"

    return {
        "topic": topic,
        "cheatsheet": cheatsheet,
        "source": source,
        "topic_from": topic_from,
    }


def _save_cheatsheet(topic_name, cheatsheet, source="ansi",
                     ip_addr=None, user_agent=None, request_path=None):
    """
    Save a submitted cheat sheet together with a structured JSON
    metadata sidecar into the spool directory.

    Returns (content_filename, metadata_filename, metadata_dict).
    """
    nonce = _generate_nonce()
    base_name = topic_name.replace("/", ".") + "." + nonce
    content_filename = os.path.join(CONFIG["path.spool"], base_name)
    metadata_filename = content_filename + ".meta.json"

    # Ensure spool directory exists
    spool_dir = CONFIG["path.spool"]
    if not os.path.exists(spool_dir):
        os.makedirs(spool_dir, exist_ok=True)

    # Write cheatsheet content
    with open(content_filename, "w", encoding="utf-8") as fh:
        fh.write(cheatsheet)

    # Build structured metadata
    metadata = {
        "topic": topic_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_format": source,
        "ip_addr": ip_addr or "unknown",
        "user_agent": user_agent or "unknown",
        "filename": base_name,
        "content_hash": _content_hash(cheatsheet),
        "content_length": len(cheatsheet),
        "is_content_empty": len(cheatsheet.strip()) == 0,
        "request_path": request_path or "",
    }

    with open(metadata_filename, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)

    return content_filename, metadata_filename, metadata


def get_recent_submissions(limit=20):
    """
    Scan the spool directory and return a list of recent submission
    metadata summaries, newest first.

    Each entry is a dict loaded from a ``.meta.json`` sidecar file.
    """
    spool_dir = CONFIG["path.spool"]
    if not os.path.exists(spool_dir):
        return []

    meta_files = [
        f for f in os.listdir(spool_dir) if f.endswith(".meta.json")
    ]
    # Sort by modification time, newest first
    meta_files.sort(
        key=lambda f: os.path.getmtime(os.path.join(spool_dir, f)),
        reverse=True,
    )

    submissions = []
    for fname in meta_files[:limit]:
        fpath = os.path.join(spool_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                submissions.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue

    return submissions


def get_submissions_report(limit=20):
    """
    Return a human-readable text report summarising the most recent
    submissions.  Suitable for display as the ``:submissions``
    internal page.
    """
    submissions = get_recent_submissions(limit=limit)

    if not submissions:
        return "No submissions yet.\n"

    lines = [
        "# Recent Submissions",
        "",
        "Total shown: %d" % len(submissions),
        "",
    ]

    for i, sub in enumerate(submissions, 1):
        empty_tag = " [EMPTY]" if sub.get("is_content_empty") else ""
        fmt_label = (
            "ANSI/CLI" if sub.get("source_format") == "ansi" else "HTML/Browser"
        )
        lines.append(
            "%d. [%s] topic=%s  ip=%s  format=%s  %d chars%s"
            % (
                i,
                sub.get("timestamp", "unknown"),
                sub.get("topic", "UNNAMED"),
                sub.get("ip_addr", "unknown"),
                fmt_label,
                sub.get("content_length", 0),
                empty_tag,
            )
        )
        lines.append("   file=%s" % sub.get("filename", "?"))
        lines.append(
            "   hash=%s" % sub.get("content_hash", "?")[:16]
        )
        lines.append("")

    return "\n".join(lines) + "\n"


def process_post_request(req, topic=None, ip_addr=None, user_agent=None):
    """
    Process a POST request through the submission pipeline.

    1. Parse topic and content from the form data.
    2. Resolve the final topic name (form > URL > default UNNAMED).
    3. Validate and save content + metadata sidecar.

    Returns a status string: "OK" or an error/warning message.
    """
    parsed = parse_submission(req)

    # Resolve final topic: form-supplied > URL path > default
    if parsed["topic"] is not None:
        final_topic = parsed["topic"]
    elif topic is not None:
        final_topic = topic
    else:
        final_topic = "UNNAMED"

    cheatsheet = parsed["cheatsheet"]
    source = parsed["source"]

    # Capture request context
    if ip_addr is None:
        ip_addr = getattr(req, "remote_addr", None) or "unknown"
    if user_agent is None:
        user_agent = req.headers.get("User-Agent", "unknown")
    request_path = getattr(req, "path", "") or ""

    # Save content + metadata sidecar
    _content_file, _meta_file, metadata = _save_cheatsheet(
        final_topic,
        cheatsheet,
        source=source,
        ip_addr=ip_addr,
        user_agent=user_agent,
        request_path=request_path,
    )

    if metadata["is_content_empty"]:
        return "WARN: empty submission saved as %s\n" % metadata["filename"]

    return "OK\n"
