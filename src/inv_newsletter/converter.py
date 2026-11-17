"""Convert HTML email body to Markdown with image extraction."""

import base64
import logging
import mimetypes
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as md

from inv_newsletter.links import clean_tracking_url
from inv_newsletter.outlook import Attachment

logger = logging.getLogger(__name__)


@dataclass
class ImageFile:
    filename: str
    data: bytes


@dataclass
class ConversionResult:
    markdown: str
    images: list[ImageFile]


def convert_email(
    html: str,
    attachments: list[Attachment],
    subject: str,
) -> ConversionResult:
    """Convert HTML email to Markdown, extracting inline images."""
    if not html:
        return ConversionResult(markdown="*(no HTML body)*", images=[])

    images: list[ImageFile] = []
    img_counter = 0

    soup = BeautifulSoup(html, "html.parser")

    # 1. Remove noise elements
    for tag in soup.find_all(["style", "script", "meta", "link"]):
        tag.decompose()

    # Remove tracking pixels (1x1 or very small images)
    for img in soup.find_all("img"):
        w = img.get("width", "")
        h = img.get("height", "")
        if w in ("1", "0") or h in ("1", "0"):
            img.decompose()

    # 2. Strip spacer/layout table cells that have no text content
    #    Instead of unwrapping whole tables (which can lose content),
    #    we remove purely empty rows to reduce noise.
    _clean_empty_table_rows(soup)

    # 2b. Unwrap subscriber click-tracking links (Substack / Resend) so the
    #     digest never carries a per-recipient URL; untrackable ones → text only.
    for a in soup.find_all("a", href=re.compile(r"substack\.com/|resend-clicks-a\.com/|slack\.com/", re.I)):
        clean = clean_tracking_url(a["href"])
        if clean is None:
            a.unwrap()
        else:
            a["href"] = clean

    # 3. Map cid: inline images to local files
    cid_map = {att.content_id: att for att in attachments if att.is_inline and att.content_id}
    for img in soup.find_all("img", src=re.compile(r"^cid:", re.I)):
        cid = img["src"][4:]  # strip "cid:"
        att = cid_map.get(cid)
        if att and att.content_bytes:
            img_counter += 1
            ext = _guess_ext(att.content_type, att.name)
            filename = f"img-{img_counter:03d}{ext}"
            images.append(ImageFile(filename=filename, data=att.content_bytes))
            img["src"] = f"./{filename}"
            img["alt"] = img.get("alt", att.name)
        else:
            img.decompose()

    # 4. Extract base64-embedded images
    for img in soup.find_all("img", src=re.compile(r"^data:image/")):
        src = img["src"]
        match = re.match(r"data:image/([^;]+);base64,(.+)", src, re.DOTALL)
        if match:
            ext = f".{match.group(1).split('+')[0]}"
            try:
                data = base64.b64decode(match.group(2))
            except Exception:
                img.decompose()
                continue
            if len(data) < 100:  # skip tiny spacer images
                img.decompose()
                continue
            img_counter += 1
            filename = f"img-{img_counter:03d}{ext}"
            images.append(ImageFile(filename=filename, data=data))
            img["src"] = f"./{filename}"
        else:
            img.decompose()

    # 4b. Substack emails reference images by URL (substackcdn) instead of
    #     cid:/base64 — download post content images, drop Substack UI icons.
    for img in soup.find_all("img", src=re.compile(r"^https?://([\w-]+\.)*substackcdn\.com/", re.I)):
        src = img["src"]
        if not _is_substack_content_image(src, img.get("width", "")):
            img.decompose()
            continue
        fetched = _fetch_remote_image(src)
        if fetched is None:
            continue  # keep the remote URL so the markdown still points somewhere
        data, content_type = fetched
        img_counter += 1
        filename = f"img-{img_counter:03d}{_guess_ext(content_type, '')}"
        images.append(ImageFile(filename=filename, data=data))
        img["src"] = f"./{filename}"

    # 5. Also save non-inline image attachments
    for att in attachments:
        if not att.is_inline and att.content_bytes and att.content_type.startswith("image/"):
            img_counter += 1
            ext = _guess_ext(att.content_type, att.name)
            filename = f"img-{img_counter:03d}{ext}"
            images.append(ImageFile(filename=filename, data=att.content_bytes))

    # 6. Remove common disclaimer / footer patterns
    _strip_disclaimers(soup)

    # 7. Convert to Markdown
    markdown = md(
        str(soup),
        heading_style="ATX",
        strip=["style", "script"],
    )

    # 8. Post-clean
    markdown = _post_clean(markdown)

    return ConversionResult(markdown=markdown, images=images)


SUBSTACK_MIN_WIDTH = 100  # declared width below this = avatar/logo, not content
REMOTE_IMAGE_TIMEOUT = 20
REMOTE_IMAGE_MAX_BYTES = 10_000_000


def _is_substack_content_image(src: str, width: str) -> bool:
    """Post images are substackcdn /image/fetch/ proxies of substack-post-media
    uploads; icons (like/comment/share) and email chrome proxy substack.com."""
    parsed = urlparse(src)
    if parsed.hostname != "substackcdn.com" or not parsed.path.startswith("/image/fetch/"):
        return False
    if "substack-post-media" not in unquote(parsed.path):
        return False
    if width.isdigit() and int(width) < SUBSTACK_MIN_WIDTH:
        return False
    return True


def _fetch_remote_image(url: str) -> tuple[bytes, str] | None:
    """Download an image; returns (bytes, content_type) or None on any failure."""
    try:
        resp = requests.get(
            url,
            timeout=REMOTE_IMAGE_TIMEOUT,
            # substackcdn f_auto negotiates format from Accept — ask for png/jpeg
            headers={"Accept": "image/png,image/jpeg;q=0.9,image/*;q=0.5"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Remote image download failed ({e}): {url[:120]}")
        return None
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if not content_type.startswith("image/") or len(resp.content) > REMOTE_IMAGE_MAX_BYTES:
        logger.warning(f"Skipping remote image ({content_type}, {len(resp.content)}B): {url[:120]}")
        return None
    return resp.content, content_type


def _clean_empty_table_rows(soup: BeautifulSoup):
    """Remove table rows where ALL cells are empty (pure spacer rows).

    This is a conservative approach: only remove rows with zero text content,
    preserving the table structure for rows that have any content at all.
    """
    for tr in soup.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        # Check if ALL cells in this row are empty (no text, no images)
        has_content = False
        for cell in cells:
            if cell.get_text(strip=True):
                has_content = True
                break
            if cell.find("img"):
                has_content = True
                break
        if not has_content:
            tr.decompose()


def _strip_disclaimers(soup: BeautifulSoup):
    """Remove common email disclaimer/footer blocks."""
    disclaimer_patterns = [
        "this email is limited to clients",
        "please do not forward",
        "this message is for the designated recipient",
        "confidential",
        "this is not research",
        "unsubscribe",
        "manage your subscriptions",
        "sales commentary only",
    ]
    for tag in soup.find_all(["div", "p", "span", "td"]):
        text = tag.get_text(strip=True).lower()
        if len(text) > 20 and any(p in text for p in disclaimer_patterns):
            # Only remove if it's near the bottom (small remaining content after it)
            remaining = tag.find_all_next(string=True)
            remaining_text = "".join(s.strip() for s in remaining)
            if len(remaining_text) < 500:
                tag.decompose()


def _post_clean(markdown: str) -> str:
    """Clean up converted Markdown."""
    lines = markdown.split("\n")
    cleaned = []
    for line in lines:
        # Skip lines that are ONLY pipes, spaces, and dashes (pure separator/empty rows)
        stripped = line.strip()
        if stripped and all(c in "| -" for c in stripped):
            continue
        # Skip lines that are a table row with ALL empty cells
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if cells and all(c == "" or c == "---" for c in cells):
                continue
        cleaned.append(line)

    markdown = "\n".join(cleaned)
    # Collapse 3+ blank lines to 2
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    # Remove trailing whitespace per line
    markdown = re.sub(r" +$", "", markdown, flags=re.MULTILINE)
    return markdown.strip()


def _guess_ext(content_type: str, name: str) -> str:
    """Guess file extension from MIME type or filename."""
    if name and "." in name:
        return "." + name.rsplit(".", 1)[-1].lower()
    ext = mimetypes.guess_extension(content_type)
    return ext or ".png"
