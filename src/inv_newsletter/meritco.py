"""Meritco (久谦) forum minutes fetcher — scrape and save as email.md for summarizer."""

import base64
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Response

logger = logging.getLogger(__name__)

BROWSER_STATE_DIR = Path(".browser_state_meritco")
BASE_URL = "https://research.meritco-group.com"
MINUTES_URL = f"{BASE_URL}/forum?forumType=2"


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    """Convert Meritco Q&A HTML to clean markdown.

    Input is structured as <h2> questions (blue) + <p> answers.
    """
    # Remove style attributes
    text = re.sub(r'\s+style="[^"]*"', "", html)
    # Convert Q headings
    text = re.sub(r"<h2[^>]*><span[^>]*>(.*?)</span></h2>", r"\n**\1**\n", text)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n**\1**\n", text)
    # Convert paragraphs
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text)
    # Convert bold/underline
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text)
    text = re.sub(r"<u>(.*?)</u>", r"\1", text)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Clean entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Browser session / API
# ---------------------------------------------------------------------------

def _launch_browser(headless: bool):
    """Launch persistent browser context. Returns (playwright, context, page)."""
    p = sync_playwright().start()
    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_STATE_DIR),
        headless=headless,
        channel="chrome",
        viewport={"width": 1440, "height": 900},
    )
    page = context.pages[0] if context.pages else context.new_page()
    return p, context, page


def _is_logged_in(page: Page) -> bool:
    page.wait_for_timeout(3000)
    url = page.url
    if "login" in url.lower() or "auth" in url.lower():
        return False
    content = page.content().lower()
    if ("扫码" in content or "微信登录" in content) and "forum" not in url:
        return False
    return True


def _login(force_visible: bool = False):
    """Login flow: headless first, then visible. Returns (playwright, context, page)."""
    if not force_visible:
        logger.info("Meritco: trying headless session...")
        p, context, page = _launch_browser(headless=True)
        page.goto(MINUTES_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if _is_logged_in(page):
            logger.info("Meritco: headless session valid")
            return p, context, page
        logger.info("Meritco: headless failed, switching to visible...")
        context.close()
        p.stop()

    print("\n" + "=" * 60)
    print("浏览器已打开，请扫码登录久谦论坛。")
    print("登录完成后脚本会自动继续（最多等待 120 秒）。")
    print("=" * 60 + "\n")

    p, context, page = _launch_browser(headless=False)
    page.goto(MINUTES_URL, wait_until="domcontentloaded")

    start = time.time()
    while (time.time() - start) < 120:
        page.wait_for_timeout(3000)
        if _is_logged_in(page):
            logger.info("Meritco: login successful")
            page.wait_for_timeout(3000)
            return p, context, page

    raise RuntimeError("久谦登录超时（120 秒），请重试。")


def _fetch_minutes_list(page: Page, target_date: str) -> list[dict]:
    """Navigate to 纪要 tab and capture the forum/select/list API response."""
    captured = []

    def handle_response(response: Response):
        if "forum/select/list" not in response.url:
            return
        try:
            body = response.json()
            items = body.get("result", {}).get("forumList", [])
            captured.extend(items)
        except Exception:
            pass

    page.on("response", handle_response)
    page.goto(MINUTES_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    page.remove_listener("response", handle_response)

    # Filter to target date
    minutes = []
    for item in captured:
        meeting_time = item.get("meetingTime", "")
        if meeting_time.startswith(target_date):
            minutes.append(item)

    logger.info(f"Meritco: {len(captured)} total minutes, {len(minutes)} on {target_date}")
    return minutes


def _fetch_detail(page: Page, item: dict) -> str | None:
    """Click into a minutes entry and capture the full content from API."""
    item_id = item.get("id")
    expert = item.get("expertInformation", "")
    content_captured = []

    def handle_response(response: Response):
        if "forum/select/id" not in response.url:
            return
        try:
            body = response.json()
            result = body.get("result", {})
            html = result.get("content", "")
            if html:
                content_captured.append(html)
        except Exception:
            pass

    page.on("response", handle_response)

    # Navigate via base64-encoded ID
    encoded_id = base64.b64encode(str(item_id).encode()).decode()
    detail_url = f"{BASE_URL}/forum?forumType=2&id={encoded_id}"
    page.goto(detail_url, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    page.remove_listener("response", handle_response)

    if content_captured:
        logger.info(f"Meritco: captured detail for [{item_id}] {expert} ({len(content_captured[0])} chars)")
        return content_captured[0]

    # Fallback: try clicking on the expert text from list page
    logger.warning(f"Meritco: no content via URL for [{item_id}], trying click...")
    page.goto(MINUTES_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    page.on("response", handle_response)
    el = page.query_selector(f"text={expert}")
    if el:
        el.click()
        page.wait_for_timeout(5000)
    page.remove_listener("response", handle_response)

    if content_captured:
        return content_captured[0]

    logger.warning(f"Meritco: failed to get content for [{item_id}]")
    return None


# ---------------------------------------------------------------------------
# Save as email.md
# ---------------------------------------------------------------------------

def _make_slug(item: dict) -> str:
    """Generate slug for Meritco minutes directory."""
    meeting_time = item.get("meetingTime", "")
    # Extract HHMM from meeting time
    try:
        dt = datetime.strptime(meeting_time, "%Y-%m-%d %H:%M:%S")
        time_prefix = dt.strftime("%H%M")
    except (ValueError, TypeError):
        time_prefix = "0000"

    expert = item.get("expertInformation", "unknown")
    # Build readable slug
    targets = item.get("relatedTargets", [])
    target_str = "-".join(t.lower() for t in targets[:3]) if targets else ""

    parts = [time_prefix]
    if target_str:
        parts.append(target_str)
    parts.append("meritco")
    return "-".join(parts)


def _save_minute_as_email(item: dict, content_html: str, base_dir: Path, target_date: str) -> Path:
    """Save a Meritco minutes entry as email.md."""
    slug = _make_slug(item)
    email_dir = base_dir / target_date / slug
    email_dir.mkdir(parents=True, exist_ok=True)

    # Convert HTML to markdown
    body_md = html_to_markdown(content_html)

    title = item.get("title", "")
    expert = item.get("expertInformation", "")
    summary = item.get("summary", "")
    targets = item.get("relatedTargets", [])
    meeting_time = item.get("meetingTime", "")
    author = item.get("author", "")
    industry = item.get("industry", "")

    # Build frontmatter matching the email.md format
    frontmatter = (
        "---\n"
        f"id: \"meritco-{item.get('id', '')}\"\n"
        f"subject: \"{_escape_yaml(title)}\"\n"
        f"sender_name: \"久谦论坛 ({expert})\"\n"
        f"sender_address: \"meritco-forum@meritco-group.com\"\n"
        f"received_at: \"{meeting_time}\"\n"
        f"fetched_at: \"{datetime.now().isoformat()}\"\n"
        f"images: []\n"
        f"source: \"meritco\"\n"
        f"tickers: {json.dumps(targets, ensure_ascii=False)}\n"
        f"industry: \"{industry}\"\n"
        "---\n\n"
    )

    # Build content with metadata header
    header = f"# {title}\n\n"
    header += f"**专家**: {expert} | **行业**: {industry} | **分析师**: {author}\n"
    if targets:
        header += f"**相关标的**: {', '.join(targets)}\n"
    header += f"**会议时间**: {meeting_time}\n\n"
    if summary:
        header += f"> **摘要**: {summary}\n\n"
    header += "---\n\n"

    md_content = frontmatter + header + body_md
    (email_dir / "email.md").write_text(md_content, encoding="utf-8")

    logger.info(f"Saved Meritco minute: {slug}")
    return email_dir


def _escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_meritco_minutes(
    base_dir: Path,
    target_date: str | None = None,
    force_visible: bool = False,
) -> list[Path]:
    """Fetch Meritco minutes for a date and save as email.md files.

    Returns list of saved directory paths.
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    p, context, page = _login(force_visible=force_visible)
    saved_dirs = []

    try:
        # Get minutes list for target date
        minutes = _fetch_minutes_list(page, target_date)
        if not minutes:
            logger.info(f"Meritco: no minutes found for {target_date}")
            return []

        logger.info(f"Meritco: fetching {len(minutes)} minutes for {target_date}")

        for item in minutes:
            item_id = item.get("id")
            # Check if already fetched
            slug = _make_slug(item)
            email_md = base_dir / target_date / slug / "email.md"
            if email_md.exists():
                logger.info(f"Meritco: skipping [{item_id}] (already exists)")
                continue

            content_html = _fetch_detail(page, item)
            if not content_html:
                continue

            path = _save_minute_as_email(item, content_html, base_dir, target_date)
            saved_dirs.append(path)

    finally:
        context.close()
        p.stop()

    logger.info(f"Meritco: saved {len(saved_dirs)} minutes to {base_dir / target_date}")
    return saved_dirs
