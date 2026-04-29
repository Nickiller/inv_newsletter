"""Meritco (久谦) forum minutes fetcher — pure HTTP + reverse-engineered signing.

Architecture:
- Playwright is used ONLY for the initial login flow (扫码 + capture token from
  localStorage). Token is cached to disk and reused for weeks.
- All API calls go through plain `requests` with the RSA-signed `X-My-Header`
  header, computed from the token + business field (forumId / page+keyword).

The signing algorithm was extracted from the frontend bundle:
  X-My-Header = base64( RSA_PKCS1v15_encrypt( token + business_field, PUBLIC_KEY ) )
"""

import base64
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://research.meritco-group.com"
API_BASE = f"{BASE_URL}/matrix-search"
MINUTES_URL = f"{BASE_URL}/forum?forumType=2"
MERITCO_DATA_DIR = Path("data/meritco")

BROWSER_STATE_DIR = Path(".browser_state_meritco")
TOKEN_CACHE_FILE = Path(".token_cache/meritco_token.json")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

# RSA-2048 public key extracted from app.d55168a2.js (chunks reversed + concat).
# Used to sign X-My-Header per request.
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0q3O3srLBw1roKRa8D8D
CUb5yy1uCZJV0WN20h7ePPj3QlUsJNKsIyuxptsV8ql2aBKjcm+tjLx8s+463m8P
MTdqoJdFaabH+dxa3/0tSMZbyWFCnm0OLzGT4PhVXxTq9MNjjIh5DZFhX5NSPtQU
8acmj2551vhzNpwnHqf6hgwVZdCUASNqqp5kOA81DYekT5soFtlZMp/StpXUHa0S
xck1rFkpwjyk0YAXwAnsTdycJovwsnbX0jwFmLqNYW3qtJYKJr5yOHRgMaNojmR/
TliA4DbroIMnChJs+5G4EFUInE6H6eTmi3CxJARDTY39MLjT8ZQGmLXdComHLCEo
LwIDAQAB
-----END PUBLIC KEY-----"""

_RSA_KEY = RSA.import_key(PUBLIC_KEY_PEM)
_CIPHER = PKCS1_v1_5.new(_RSA_KEY)


def _sign(plaintext: str) -> str:
    """Return base64(RSA_PKCS1v15_encrypt(plaintext, PUBLIC_KEY))."""
    return base64.b64encode(_CIPHER.encrypt(plaintext.encode())).decode()


# ---------------------------------------------------------------------------
# Token cache + login
# ---------------------------------------------------------------------------

def _load_cached_token() -> str | None:
    if not TOKEN_CACHE_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_FILE.read_text())
        return data.get("token")
    except Exception as e:
        logger.warning(f"Meritco: failed to read token cache: {e}")
        return None


def _save_token(token: str) -> None:
    TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_FILE.write_text(json.dumps({
        "token": token,
        "saved_at": datetime.now().isoformat(),
    }))
    logger.info(f"Meritco: token cached to {TOKEN_CACHE_FILE}")


def _login_capture_token(force_visible: bool = False) -> str:
    """Launch Playwright to login and grab token from localStorage.

    Tries headless first (using persistent browser state), falls back to visible
    so user can scan the WeChat QR code.
    """
    from playwright.sync_api import sync_playwright

    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Headless attempt first
        if not force_visible:
            logger.info("Meritco: trying headless session for token capture...")
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_STATE_DIR),
                headless=True,
                channel="chrome",
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(MINUTES_URL, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                token = page.evaluate("() => window.localStorage.getItem('token')")
                if token and token != "ceshitoken":
                    logger.info("Meritco: headless session valid, captured token")
                    ctx.close()
                    return token
            except Exception as e:
                logger.info(f"Meritco: headless capture failed ({e}), switching to visible")
            ctx.close()

        # Visible login
        print("\n" + "=" * 60)
        print("浏览器已打开，请用微信扫码登录久谦论坛。")
        print("登录完成后脚本会自动捕获 token（最多等待 120 秒）。")
        print("=" * 60 + "\n")

        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_STATE_DIR),
            headless=False,
            channel="chrome",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(MINUTES_URL, wait_until="domcontentloaded")

        deadline = time.time() + 120
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            try:
                token = page.evaluate("() => window.localStorage.getItem('token')")
                if token and token != "ceshitoken":
                    logger.info("Meritco: login successful, captured token")
                    ctx.close()
                    return token
            except Exception:
                continue

        ctx.close()
        raise RuntimeError("久谦登录超时（120 秒），请重试。")


def _get_token(force_relogin: bool = False) -> str:
    """Return a valid Meritco session token, logging in if needed."""
    if not force_relogin:
        token = _load_cached_token()
        if token:
            return token
    token = _login_capture_token(force_visible=False)
    _save_token(token)
    return token


# ---------------------------------------------------------------------------
# API calls (signed)
# ---------------------------------------------------------------------------

def _common_headers(token: str) -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN",
        "content-type": "application/json;charset=UTF-8",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
        "token": token,
        "user-agent": USER_AGENT,
    }


def _post_signed(url: str, token: str, body: dict, sign_input: str) -> dict:
    """POST a signed request. Raises on non-200 or auth failure."""
    headers = _common_headers(token)
    headers["x-my-header"] = _sign(sign_input)
    r = requests.post(
        url,
        headers=headers,
        cookies={"X-User-Type": "default"},
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _fetch_minutes_list(token: str, page: int = 1, page_size: int = 50) -> list[dict]:
    """POST /forum/select/list — sign input is token + keyword + page."""
    body = {
        "forumId": None,
        "page": page,
        "pageSize": page_size,
        "module": "CLASSIC_ALL_SEARCH",
        "contentTag": "",
        "publishTime": "",
        "codeIndustryId": "",
        "totalPage": "5",
        "sortColumn": "articleDate",
        "source": "",
        "reportTag": "全部标签",
        "platformArr": [
            "专业内容-纪要-国内市场-专家访谈",
            "专业内容-纪要-国内市场-业绩交流",
            "专业内容-纪要-国内市场-券商路演",
            "专业内容-纪要-海外市场",
            "专业内容-研报-国内市场",
            "专业内容-研报-海外市场",
            "专业内容-其他报告",
        ],
        "outCat1": "",
        "orgNameList": [],
        "outCat2": "",
        "keyword": "",
        "type": 2,
        "industryList": [],
        "expertType": "",
        "meetingStartTime": "",
        "meetingEndTime": "",
        "queryHotListFlag": False,
        "sort": 2,
        "platform": "RESEARCH_PC",
    }
    keyword = body["keyword"]
    sign_input = token + str(keyword) + str(page)
    resp = _post_signed(f"{API_BASE}/forum/select/list", token, body, sign_input)
    if resp.get("code") != 200:
        raise RuntimeError(f"Meritco list API error: {resp.get('message')}")
    return resp.get("result", {}).get("forumList", [])


def _fetch_minute_detail(token: str, forum_id: int) -> str | None:
    """POST /forum/select/id?forumId=X — sign input is token + forumId."""
    body = {"platform": "RESEARCH_PC"}
    sign_input = token + str(forum_id)
    url = f"{API_BASE}/forum/select/id?forumId={forum_id}"
    resp = _post_signed(url, token, body, sign_input)
    if resp.get("code") != 200:
        logger.warning(f"Meritco detail API error for {forum_id}: {resp.get('message')}")
        return None
    result = resp.get("result") or {}
    return result.get("content") or None


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    """Convert Meritco Q&A HTML to clean markdown.

    Input is structured as <h2> questions (blue) + <p> answers.
    """
    text = re.sub(r'\s+style="[^"]*"', "", html)
    text = re.sub(r"<h2[^>]*><span[^>]*>(.*?)</span></h2>", r"\n**\1**\n", text)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n**\1**\n", text)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text)
    text = re.sub(r"<u>(.*?)</u>", r"\1", text)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Save as markdown file
# ---------------------------------------------------------------------------

def _haiku_topic(item: dict) -> str:
    """Call Claude Haiku to extract a short topic (~30 chars) from the minute.

    Tickers and date are NOT included here — those are added separately by
    _make_filename for cleaner separation. Falls back to title prefix on error.
    """
    title = item.get("title", "")
    summary = item.get("summary", "")
    expert = item.get("expertInformation", "")

    prompt = (
        f"为以下久谦专家纪要提取一个简短的核心主题，要求：\n"
        f"1. 突出最关键的结论或讨论焦点\n"
        f"2. 中文为主，可夹带必要英文术语\n"
        f"3. 不超过 20 个字符（含标点）\n"
        f"4. 不含路径分隔符 / \\ : 等\n\n"
        f"专家：{expert}\n"
        f"标题：{title}\n"
        f"摘要：{summary[:300]}\n\n"
        f"只输出主题，不加任何前后缀和解释。"
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
        topic = resp.content[0].text.strip()
        topic = re.sub(r'[\\/*?:"<>|]', "", topic)
        topic = re.sub(r"\s+", "_", topic.strip())
        return topic[:40]
    except Exception as e:
        logger.warning(f"Haiku topic generation failed: {e}, falling back to title prefix")
        fallback = re.sub(r'[\\/*?:"<>|]', "", title)
        fallback = re.sub(r"\s+", "_", fallback.strip())
        return fallback[:30]


def _make_filename(item: dict, target_date: str) -> str:
    """Generate filename: YYMMDD_{Tickers}_{Topic}.md"""
    yymmdd = target_date.replace("-", "")[2:]
    targets = item.get("relatedTargets") or []
    tickers_part = "_".join(targets) if targets else "NoTicker"
    topic = _haiku_topic(item)
    return f"{yymmdd}_{tickers_part}_{topic}.md"


def _escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _existing_item_ids(date_dir: Path) -> set[int]:
    """Scan a date dir and return the set of meritco item_ids already saved.

    Reads each .md's YAML frontmatter and extracts the integer from `id: meritco-<N>`.
    Used for deduplication — filenames include a non-deterministic Haiku-generated
    topic so we cannot dedup by filename equality.
    """
    ids: set[int] = set()
    if not date_dir.exists():
        return ids
    for md in date_dir.glob("*.md"):
        try:
            head = md.read_text(encoding="utf-8")[:512]
            m = re.search(r'id:\s*"?meritco-(\d+)"?', head)
            if m:
                ids.add(int(m.group(1)))
        except Exception as e:
            logger.warning(f"Failed to read {md} for id dedup: {e}")
    return ids


def _save_minute(item: dict, content_html: str, base_dir: Path, target_date: str) -> Path:
    date_dir = base_dir / target_date
    date_dir.mkdir(parents=True, exist_ok=True)

    filename = _make_filename(item, target_date)
    out_path = date_dir / filename

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_meritco_minutes(
    base_dir: Path = MERITCO_DATA_DIR,
    target_date: str | None = None,
    force_visible: bool = False,
    exclude_industries: list[str] | None = None,
) -> list[Path]:
    """Fetch Meritco minutes for a date and save as markdown files.

    Args:
        force_visible: If True, force re-login via visible browser (token refresh).
        exclude_industries: Industry keywords to skip (e.g. ["医疗", "医药", "健康"]).
    Returns list of saved file paths.
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    # Get token (cached or fresh login)
    if force_visible:
        token = _login_capture_token(force_visible=True)
        _save_token(token)
    else:
        token = _get_token()

    saved_paths: list[Path] = []

    # Try fetching list; on auth failure, re-login once and retry
    try:
        minutes = _fetch_minutes_list(token)
    except (requests.HTTPError, RuntimeError) as e:
        logger.warning(f"Meritco: list fetch failed ({e}), re-logging in...")
        token = _login_capture_token(force_visible=False)
        _save_token(token)
        minutes = _fetch_minutes_list(token)

    # Filter to target date
    minutes = [m for m in minutes if (m.get("meetingTime") or "").startswith(target_date)]
    logger.info(f"Meritco: {len(minutes)} minutes on {target_date}")

    if not minutes:
        return []

    if exclude_industries:
        before = len(minutes)
        minutes = [
            m for m in minutes
            if not any(kw in (m.get("industry") or "") for kw in exclude_industries)
        ]
        logger.info(f"Meritco: excluded {before - len(minutes)} items by industry filter")

    existing_ids = _existing_item_ids(base_dir / target_date)

    for item in minutes:
        item_id = item.get("id")
        if item_id in existing_ids:
            logger.info(f"Meritco: skipping [{item_id}] (id already in dir)")
            continue

        try:
            content_html = _fetch_minute_detail(token, item_id)
        except requests.HTTPError as e:
            logger.warning(f"Meritco: detail fetch failed for [{item_id}]: {e}")
            continue

        if not content_html:
            logger.warning(f"Meritco: no content for [{item_id}]")
            continue

        path = _save_minute(item, content_html, base_dir, target_date)
        saved_paths.append(path)

    logger.info(f"Meritco: saved {len(saved_paths)} minutes to {base_dir / target_date}")
    return saved_paths
