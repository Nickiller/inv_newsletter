"""Publish a daily digest markdown to Feishu/Lark using lark-cli.

Workflow:
1. Pre-process markdown: wrap `## 今日要点` body in <callout>, append `## 信息来源` footer
2. Parse markdown into text/image segments
3. Create Lark doc with title (and first text segment)
4. For each subsequent segment: append text via `docs +update`, or insert image via `docs +media-insert`
5. Image paths in markdown are resolved relative to the .md file, then re-mapped to cwd-relative paths

Note: lark-cli requires the file path to be relative to the current working directory.
"""

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from inv_newsletter.timing import get_timer

logger = logging.getLogger(__name__)

IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
TLDR_PATTERN = re.compile(
    r"(^## 今日要点[^\n]*\n\n?)(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
MERITCO_URL_TEMPLATE = "https://research.meritco-group.com/forum?forumType=2&forumId={id}"


def publish_digest(md_path: Path, title: str | None = None, folder_token: str | None = None) -> dict:
    """Publish markdown file to Lark. Returns {doc_id, doc_url}."""
    with get_timer().phase("lark_publish", "cpu"):
        return _publish_digest_impl(md_path, title, folder_token)


def _publish_digest_impl(md_path: Path, title: str | None, folder_token: str | None) -> dict:
    md_path = Path(md_path).resolve()
    if not md_path.exists():
        raise FileNotFoundError(md_path)

    md_text = md_path.read_text(encoding="utf-8")
    if title is None:
        title = md_path.stem  # e.g. 2026-04-10_daily_digest

    # Pre-process: wrap TL;DR in callout block + append sources footer
    md_text = _wrap_tldr_in_callout(md_text)
    date_str = _extract_date(md_path)
    if date_str:
        try:
            sources = _load_sources(date_str, Path.cwd())
            sources_md = _render_sources_section(sources)
            if sources_md:
                md_text = md_text.rstrip() + "\n\n" + sources_md
                logger.info(
                    f"Appended sources footer: {len(sources['emails'])} emails + "
                    f"{len(sources['meritco'])} meritco entries"
                )
        except Exception as e:
            logger.warning(f"Failed to load source metadata for {date_str}: {e}")

    segments = _split_segments(md_text, md_path.parent)
    if not segments:
        raise RuntimeError("No content found in markdown")

    # Create doc with first text segment (or empty if first is image)
    first_text = ""
    start_idx = 0
    if segments[0][0] == "text":
        first_text = segments[0][1]
        start_idx = 1

    logger.info(f"Creating Lark doc: {title}")
    create_result = _lark_create(title, first_text, folder_token)
    doc_id = create_result["doc_id"]
    doc_url = create_result["doc_url"]
    logger.info(f"Created: {doc_url}")

    # Process remaining segments
    for kind, payload in segments[start_idx:]:
        if kind == "text":
            if payload.strip():
                logger.debug(f"Appending text ({len(payload)} chars)")
                _lark_append(doc_id, payload)
        elif kind == "image":
            img_path: Path = payload
            if not img_path.exists():
                logger.warning(f"Image not found, skipping: {img_path}")
                continue
            try:
                rel_path = img_path.relative_to(Path.cwd())
            except ValueError:
                logger.warning(f"Image not under cwd, skipping: {img_path}")
                continue
            logger.info(f"Inserting image: {rel_path}")
            _lark_media_insert(doc_id, rel_path)

    try:
        _lark_set_public_link(doc_id)
        logger.info("Set link permission: anyone_readable")
    except Exception as e:
        logger.warning(f"Failed to set public link permission: {e}")

    return {"doc_id": doc_id, "doc_url": doc_url}


def _extract_title(md_text: str) -> str | None:
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_date(md_path: Path) -> str | None:
    """Extract YYYY-MM-DD from filename like 2026-05-13_daily_digest_v3.md."""
    m = DATE_PATTERN.match(md_path.name)
    return m.group(1) if m else None


def _wrap_tldr_in_callout(md_text: str) -> str:
    """Wrap `## 今日要点` body (until next ##) in a Lark callout block.

    Header stays outside callout so it appears in the doc's TOC. Only the bullets
    + sub-bullets go into the colored highlight block.
    """
    def replace(m):
        header = m.group(1)
        body = m.group(2).rstrip()
        if not body:
            return m.group(0)
        return (
            f"{header}"
            f'<callout emoji="📌" background-color="light-yellow" border-color="yellow">\n'
            f"{body}\n"
            f"</callout>\n\n"
        )
    return TLDR_PATTERN.sub(replace, md_text, count=1)


def _parse_yaml_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


def _meritco_id_to_url(meritco_id) -> str | None:
    m = re.search(r"(\d+)", str(meritco_id or ""))
    return MERITCO_URL_TEMPLATE.format(id=m.group(1)) if m else None


def _load_sources(date_str: str, project_root: Path, meritco_days: int = 3) -> dict:
    """Load email + meritco metadata for the digest date.

    Returns {"emails": [...], "meritco": [...]} where each entry has the fields
    needed to render the source footer (subject, sender, time, source_url where
    available).
    """
    emails: list[dict] = []
    mail_dir = project_root / "data" / "mail" / date_str
    if mail_dir.exists():
        for email_md in sorted(mail_dir.glob("*/email.md")):
            try:
                raw = email_md.read_text(encoding="utf-8")
                fm, _ = _parse_yaml_frontmatter(raw)
                emails.append({
                    "subject": fm.get("subject", "") or "",
                    "sender_name": fm.get("sender_name", "") or "",
                    "received_at": fm.get("received_at", "") or "",
                })
            except Exception as e:
                logger.debug(f"Failed to read email metadata from {email_md}: {e}")

    meritco: list[dict] = []
    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        target_dt = None
    if target_dt is not None:
        for offset in range(meritco_days):
            d = target_dt - timedelta(days=offset)
            day_dir = project_root / "data" / "meritco" / d.isoformat()
            if not day_dir.exists():
                continue
            for md_file in sorted(day_dir.glob("*.md")):
                try:
                    raw = md_file.read_text(encoding="utf-8")
                    fm, _ = _parse_yaml_frontmatter(raw)
                    meritco.append({
                        "subject": fm.get("subject", "") or "",
                        "tickers": fm.get("tickers", []) or [],
                        "date": d.isoformat(),
                        "source_url": _meritco_id_to_url(fm.get("id", "")),
                    })
                except Exception as e:
                    logger.debug(f"Failed to read meritco metadata from {md_file}: {e}")

    return {"emails": emails, "meritco": meritco}


def _render_sources_section(sources: dict) -> str:
    """Render the markdown for the `## 信息来源` footer section."""
    if not sources.get("emails") and not sources.get("meritco"):
        return ""
    lines = ["---", "", "## 信息来源", ""]
    emails = sources.get("emails", [])
    if emails:
        lines.append(f"### 邮件（{len(emails)} 封）")
        lines.append("")
        for e in emails:
            received = e.get("received_at", "")
            time_str = received[:16].replace("T", " ") if received else ""
            sender = e.get("sender_name", "—")
            subject = e.get("subject", "—")
            time_prefix = f"*{time_str}* · " if time_str else ""
            lines.append(f"- {time_prefix}**{sender}**：{subject}")
        lines.append("")
    meritco = sources.get("meritco", [])
    if meritco:
        lines.append(f"### 久谦纪要（{len(meritco)} 条）")
        lines.append("")
        for m in meritco:
            tickers = m.get("tickers") or []
            tickers_str = "/".join(tickers) if tickers else "—"
            date_str = m.get("date", "")
            date_prefix = f"*{date_str}* · " if date_str else ""
            subject = m.get("subject", "—")
            url = m.get("source_url")
            if url:
                lines.append(f"- {date_prefix}{tickers_str} · [{subject}]({url})")
            else:
                lines.append(f"- {date_prefix}{tickers_str} · {subject}")
        lines.append("")
    return "\n".join(lines)


def _split_segments(md_text: str, base_dir: Path) -> list[tuple[str, object]]:
    """Split markdown into [(kind, payload), ...] segments.

    kind="text" → payload is the markdown text chunk
    kind="image" → payload is the resolved absolute Path to the image
    Only local image references are extracted as image segments; remote URLs stay inline as text.
    """
    segments: list[tuple[str, object]] = []
    last = 0
    for m in IMG_PATTERN.finditer(md_text):
        ref = m.group(2).strip()
        # Skip remote images — keep them inline as part of text
        if ref.startswith(("http://", "https://", "data:")):
            continue

        text_before = md_text[last:m.start()]
        if text_before:
            segments.append(("text", text_before))

        img_abs = (base_dir / ref).resolve()
        segments.append(("image", img_abs))
        last = m.end()

    if last < len(md_text):
        tail = md_text[last:]
        if tail:
            segments.append(("text", tail))

    return segments


def _run_lark(args: list[str]) -> dict:
    """Run lark-cli command and parse JSON response."""
    cmd = ["lark-cli", *args, "--as", "user"]
    logger.debug(f"$ {' '.join(str(a) for a in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli failed: {result.stderr or result.stdout}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"lark-cli returned non-JSON output: {result.stdout}") from e
    if not data.get("ok"):
        raise RuntimeError(f"lark-cli error: {data.get('error') or data}")
    return data["data"]


def _lark_create(title: str, markdown: str, folder_token: str | None) -> dict:
    args = ["docs", "+create", "--title", title, "--markdown", markdown]
    if folder_token:
        args.extend(["--folder-token", folder_token])
    return _run_lark(args)


def _lark_append(doc_id: str, markdown: str) -> dict:
    return _run_lark(["docs", "+update", "--doc", doc_id, "--mode", "append", "--markdown", markdown])


def _lark_set_public_link(doc_id: str) -> dict:
    """Set doc link permission to 'anyone with the link can read'.

    Uses the raw api command, which returns native Lark `{code, data, msg}` format
    rather than the wrapper's `{ok, data}` format, so we bypass _run_lark.
    """
    cmd = [
        "lark-cli", "api", "PATCH",
        f"/open-apis/drive/v2/permissions/{doc_id}/public",
        "--params", '{"type":"docx"}',
        "--data", '{"link_share_entity":"anyone_readable"}',
        "--as", "user",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli failed: {result.stderr or result.stdout}")
    data = json.loads(result.stdout)
    if data.get("code") != 0:
        raise RuntimeError(f"lark api error: {data.get('msg') or data}")
    return data.get("data", {})


def _lark_media_insert(doc_id: str, file_path: Path) -> dict:
    return _run_lark([
        "docs", "+media-insert",
        "--doc", doc_id,
        "--file", str(file_path),
        "--align", "center",
    ])
