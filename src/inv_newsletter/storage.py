"""Save emails as Markdown files with deduplication."""

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from inv_newsletter.converter import ConversionResult
from inv_newsletter.fomo_format import is_fomo_email, reformat_content
from inv_newsletter.outlook import Email

logger = logging.getLogger(__name__)

FETCHED_IDS_FILE = ".fetched_ids.json"


def save_email(email: Email, result: ConversionResult, base_dir: Path) -> Path:
    """Save email as .md with images to date-based subdirectory. Returns the directory path."""
    date_str = email.received_at.strftime("%Y-%m-%d")
    slug = _make_slug(email.subject, email.sender_address, email.received_at)
    email_dir = base_dir / date_str / slug
    email_dir.mkdir(parents=True, exist_ok=True)

    # Write images
    image_names = []
    for img in result.images:
        (email_dir / img.filename).write_bytes(img.data)
        image_names.append(img.filename)

    # Build frontmatter
    frontmatter = (
        "---\n"
        f"id: \"{email.id[:50]}...\"\n"
        f"subject: \"{_escape_yaml(email.subject)}\"\n"
        f"sender_name: \"{_escape_yaml(email.sender_name)}\"\n"
        f"sender_address: \"{email.sender_address}\"\n"
        f"received_at: \"{email.received_at.isoformat()}\"\n"
        f"fetched_at: \"{datetime.now(timezone.utc).isoformat()}\"\n"
        f"images: {json.dumps(image_names)}\n"
        "---\n\n"
    )

    # Write email.md
    md_content = frontmatter + f"# {email.subject}\n\n" + result.markdown
    if is_fomo_email(email.sender_address):
        md_content = reformat_content(md_content)
    (email_dir / "email.md").write_text(md_content, encoding="utf-8")

    logger.info(f"Saved: {email_dir.relative_to(base_dir)}")
    return email_dir


def is_already_fetched(email_id: str, base_dir: Path) -> bool:
    ids = _load_fetched_ids(base_dir)
    return email_id in ids


def mark_fetched(email_id: str, path: str, base_dir: Path):
    ids = _load_fetched_ids(base_dir)
    ids[email_id] = path
    _save_fetched_ids(ids, base_dir)


def _load_fetched_ids(base_dir: Path) -> dict:
    fpath = base_dir / FETCHED_IDS_FILE
    if not fpath.exists():
        return {}
    try:
        return json.loads(fpath.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_fetched_ids(ids: dict, base_dir: Path):
    fpath = base_dir / FETCHED_IDS_FILE
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(json.dumps(ids, indent=2), encoding="utf-8")


def _make_slug(subject: str, sender_address: str, received_at: datetime) -> str:
    """Generate filesystem-safe directory name.

    Example: '0901-crwd-this-is-where-we-hold-them-wolferesearch'
    """
    time_prefix = received_at.strftime("%H%M")

    # Extract sender domain without TLD
    domain = ""
    if "@" in sender_address:
        domain_full = sender_address.split("@")[1]
        domain = domain_full.split(".")[0]

    # Slugify subject
    text = unicodedata.normalize("NFKD", subject)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    text = text[:60]  # truncate
    text = text.rstrip("-")

    parts = [time_prefix, text]
    if domain:
        parts.append(domain)
    return "-".join(parts)


def _escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
