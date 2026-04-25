"""Meritco (久谦) forum minutes fetcher — scrape and save as email.md for summarizer."""

import base64
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import anthropic
from playwright.sync_api import sync_playwright, Page, Response

logger = logging.getLogger(__name__)

BROWSER_STATE_DIR = Path(".browser_state_meritco")
BASE_URL = "https://research.meritco-group.com"
MINUTES_URL = f"{BASE_URL}/forum?forumType=2"
MERITCO_DATA_DIR = Path("data/meritco")


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
        try:
            page.goto(MINUTES_URL, wait_until="networkidle", timeout=20000)
        except Exception:
            # networkidle can timeout if page keeps polling; fall back
            pass
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
    """Navigate to 纪要 tab and capture the forum/select/list API response.

    Key reliability notes (learned from debugging):
    - Must use wait_until='networkidle' so XHR responses complete before we read them
    - Must NOT call page.goto() again while response handler is active —
      navigating away invalidates response body buffers, causing response.json() to fail
    - Must log exceptions from response.json(), never silently swallow them
    """
    captured = []

    def handle_response(response: Response):
        if "forum/select/list" not in response.url:
            return
        try:
            body = response.json()
            items = body.get("result", {}).get("forumList", [])
            captured.extend(items)
            logger.debug(f"Meritco: list API returned {len(items)} items")
        except Exception as e:
            logger.warning(f"Meritco: failed to parse list API response: {e}")

    page.on("response", handle_response)
    # networkidle ensures all XHR/Fetch complete before returning,
    # so response.json() can read the body reliably
    page.goto(MINUTES_URL, wait_until="networkidle", timeout=30000)
    page.remove_listener("response", handle_response)

    # Filter to target date
    minutes = [
        item for item in captured
        if item.get("meetingTime", "").startswith(target_date)
    ]

    logger.info(f"Meritco: {len(captured)} total minutes, {len(minutes)} on {target_date}")
    return minutes


def _fetch_detail(page: Page, item: dict) -> str | None:
    """Navigate to a minutes detail page and capture the full content from API.

    Uses networkidle to ensure response body is available before reading.
    Does NOT navigate away until response is captured.
    """
    item_id = item.get("id")
    expert = item.get("expertInformation", "")
    content_captured = []

    def handle_response(response: Response):
        if "/forum/" in response.url or "forum/select" in response.url:
            logger.debug(f"Meritco: response url [{item_id}]: {response.url} status={response.status}")
        if "forum/select/id" not in response.url:
            return
        try:
            body = response.json()
            result = body.get("result", {})
            html = result.get("content", "")
            logger.debug(f"Meritco: detail response [{item_id}]: result keys={list(result.keys())}, content len={len(html)}")
            if html:
                content_captured.append(html)
            else:
                logger.warning(f"Meritco: empty content field for [{item_id}], result={result}")
        except Exception as e:
            logger.warning(f"Meritco: failed to parse detail API response for [{item_id}]: {e}")

    page.on("response", handle_response)

    # Navigate via base64-encoded ID — use networkidle so response body is readable
    encoded_id = base64.b64encode(str(item_id).encode()).decode()
    detail_url = f"{BASE_URL}/forum?forumType=2&id={encoded_id}"
    page.goto(detail_url, wait_until="networkidle", timeout=30000)
    page.remove_listener("response", handle_response)

    if content_captured:
        logger.info(f"Meritco: captured detail for [{item_id}] {expert} ({len(content_captured[0])} chars)")
        return content_captured[0]

    # Fallback: navigate to list, click the expert text to trigger detail API
    logger.warning(f"Meritco: no content via URL for [{item_id}], trying click fallback...")

    page.on("response", handle_response)
    page.goto(MINUTES_URL, wait_until="networkidle", timeout=30000)
    el = page.query_selector(f"text={expert}")
    if el:
        el.click()
        # Wait for the detail API response (no page navigation, just XHR)
        page.wait_for_timeout(5000)
    page.remove_listener("response", handle_response)

    if content_captured:
        logger.info(f"Meritco: captured detail via click for [{item_id}] ({len(content_captured[0])} chars)")
        return content_captured[0]

    logger.warning(f"Meritco: failed to get content for [{item_id}]")
    return None


# ---------------------------------------------------------------------------
# Save as email.md
# ---------------------------------------------------------------------------

def _haiku_slug(item: dict) -> str:
    """Call Claude Haiku to generate a short filename slug with tickers."""
    title = item.get("title", "")
    summary = item.get("summary", "")
    targets = item.get("relatedTargets", [])
    expert = item.get("expertInformation", "")

    ticker_str = "/".join(targets[:4]) if targets else ""
    prompt = (
        f"为以下久谦专家纪要生成一个简短英文文件名（不含扩展名），要求：\n"
        f"1. 包含相关Ticker（如有），格式：TICKER1_TICKER2_核心主题\n"
        f"2. 核心主题用英文或拼音，3-6个词，突出最关键结论\n"
        f"3. 只用字母、数字、下划线，不含空格和特殊字符\n"
        f"4. 总长度不超过50个字符\n\n"
        f"Ticker: {ticker_str}\n"
        f"专家: {expert}\n"
        f"标题: {title}\n"
        f"摘要: {summary[:200]}\n\n"
        f"只输出文件名，不加任何解释。"
    )

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        slug = resp.content[0].text.strip()
        # Extra sanitize
        slug = re.sub(r'[^A-Za-z0-9_\-]', "_", slug)
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug[:60]
    except Exception as e:
        logger.warning(f"Haiku slug generation failed: {e}, falling back to title")
        fallback = re.sub(r'[\\/*?:"<>|]', "", title)
        fallback = re.sub(r"\s+", "_", fallback.strip())
        return fallback[:50]


def _make_filename(item: dict, target_date: str) -> str:
    """Generate filename: [YYMMDD]_meritco_{haiku_slug}.md"""
    yymmdd = target_date.replace("-", "")[2:]  # 2026-04-23 → 260423
    slug = _haiku_slug(item)
    return f"[{yymmdd}]_meritco_{slug}.md"


def _save_minute(item: dict, content_html: str, base_dir: Path, target_date: str) -> Path:
    """Save a Meritco minutes entry as [YYMMDD]_meritco_{title}.md."""
    date_dir = base_dir / target_date
    date_dir.mkdir(parents=True, exist_ok=True)

    filename = _make_filename(item, target_date)
    out_path = date_dir / filename

    # Convert HTML to markdown
    body_md = html_to_markdown(content_html)

    title = item.get("title", "")
    expert = item.get("expertInformation", "")
    summary = item.get("summary", "")
    targets = item.get("relatedTargets", [])
    meeting_time = item.get("meetingTime", "")
    author = item.get("author", "")
    industry = item.get("industry", "")

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

    header = f"# {title}\n\n"
    header += f"**专家**: {expert} | **行业**: {industry} | **分析师**: {author}\n"
    if targets:
        header += f"**相关标的**: {', '.join(targets)}\n"
    header += f"**会议时间**: {meeting_time}\n\n"
    if summary:
        header += f"> **摘要**: {summary}\n\n"
    header += "---\n\n"

    out_path.write_text(frontmatter + header + body_md, encoding="utf-8")
    logger.info(f"Saved Meritco minute: {filename}")
    return out_path


def _escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_meritco_minutes(
    base_dir: Path = MERITCO_DATA_DIR,
    target_date: str | None = None,
    force_visible: bool = False,
    exclude_industries: list[str] | None = None,
) -> list[Path]:
    """Fetch Meritco minutes for a date and save as email.md files.

    Args:
        exclude_industries: Industry keywords to skip (e.g. ["医疗", "医药", "健康"]).
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

        # Filter out excluded industries
        if exclude_industries:
            before = len(minutes)
            minutes = [
                item for item in minutes
                if not any(kw in (item.get("industry") or "") for kw in exclude_industries)
            ]
            logger.info(f"Meritco: excluded {before - len(minutes)} items by industry filter")

        logger.info(f"Meritco: fetching {len(minutes)} minutes for {target_date}")

        for item in minutes:
            item_id = item.get("id")
            # Check if already fetched
            filename = _make_filename(item, target_date)
            out_path = base_dir / target_date / filename
            if out_path.exists():
                logger.info(f"Meritco: skipping [{item_id}] (already exists)")
                continue

            content_html = _fetch_detail(page, item)
            if not content_html:
                continue

            path = _save_minute(item, content_html, base_dir, target_date)
            saved_dirs.append(path)

    finally:
        context.close()
        p.stop()

    logger.info(f"Meritco: saved {len(saved_dirs)} minutes to {base_dir / target_date}")
    return saved_dirs
