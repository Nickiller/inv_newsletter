# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Meritco 卖方研究论坛探索性抓取脚本。

首次运行：visible 模式扫码登录，session 持久化。
后续运行：headless 复用 session cookies。

用法：
    uv run scripts/meritco_explore.py           # 自动模式（先 headless，失败则 visible）
    uv run scripts/meritco_explore.py --visible  # 强制 visible 模式
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page, BrowserContext, Response

BROWSER_STATE_DIR = Path(".browser_state_meritco")
DATA_DIR = Path("data/meritco")
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
FORUM_URL = "https://research.meritco-group.com/forum?forumType=3"
LOGIN_URL = "https://research.meritco-group.com"


def setup_dirs():
    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def is_logged_in(page: Page) -> bool:
    """Check if we're logged in by looking for login/scan-code indicators."""
    # Wait a bit for SPA to render
    page.wait_for_timeout(3000)
    url = page.url
    # If redirected to login page, not logged in
    if "login" in url.lower() or "auth" in url.lower():
        return False
    # Check for common login prompts (WeChat QR, etc.)
    content = page.content().lower()
    if "扫码" in content or "微信登录" in content or "scan" in content:
        # Could be on the main page with a login modal
        # Check if forum content is also present
        if "forum" not in url:
            return False
    return True


def launch_browser(headless: bool) -> tuple:
    """Launch persistent browser context. Returns (playwright, context, page)."""
    p = sync_playwright().start()
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_STATE_DIR),
        headless=headless,
        channel="chrome",
        viewport={"width": 1440, "height": 900},
    )
    page = context.pages[0] if context.pages else context.new_page()
    return p, context, page


def login(force_visible: bool = False) -> tuple:
    """Login flow: try headless first, fall back to visible if needed."""
    if not force_visible:
        print("尝试 headless 模式（复用已有 session）...")
        p, context, page = launch_browser(headless=True)
        page.goto(FORUM_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)  # Wait for SPA + redirects

        if is_logged_in(page):
            print("✓ Headless 登录成功，session 有效")
            return p, context, page

        print("Headless session 失效，切换到 visible 模式...")
        context.close()
        p.stop()

    # Visible mode for manual login
    print("\n" + "=" * 60)
    print("浏览器已打开，请扫码登录 Meritco 论坛。")
    print("登录完成后脚本会自动继续（最多等待 120 秒）。")
    print("=" * 60 + "\n")

    p, context, page = launch_browser(headless=False)
    page.goto(FORUM_URL, wait_until="domcontentloaded")

    # Wait for user to login
    start = time.time()
    while (time.time() - start) < 120:
        page.wait_for_timeout(3000)
        if is_logged_in(page):
            print("✓ 登录成功！")
            # Give SPA time to fully load
            page.wait_for_timeout(3000)
            return p, context, page

    raise RuntimeError("登录超时（120 秒），请重试。")


def intercept_api(page: Page) -> list[dict]:
    """Set up request/response interception to capture API patterns."""
    api_log = []

    def handle_response(response: Response):
        url = response.url
        parsed = urlparse(url)
        # Skip static assets
        if any(ext in parsed.path for ext in [".js", ".css", ".png", ".jpg", ".svg", ".ico", ".woff"]):
            return
        # Capture API-like requests (XHR/Fetch with JSON responses)
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or "/api/" in url:
            try:
                body = response.json() if "json" in content_type else None
            except Exception:
                body = None
            entry = {
                "timestamp": datetime.now().isoformat(),
                "method": response.request.method,
                "url": url,
                "status": response.status,
                "content_type": content_type,
                "response_preview": _truncate_response(body),
            }
            api_log.append(entry)
            print(f"  API: {entry['method']} {parsed.path} → {response.status}")

    page.on("response", handle_response)
    return api_log


def _truncate_response(body, max_items: int = 3, max_str_len: int = 200) -> any:
    """Truncate response body for logging (keep structure, reduce size)."""
    if body is None:
        return None
    if isinstance(body, list):
        return body[:max_items]
    if isinstance(body, dict):
        return {k: _truncate_response(v, max_items, max_str_len) for k, v in list(body.items())[:10]}
    if isinstance(body, str) and len(body) > max_str_len:
        return body[:max_str_len] + "..."
    return body


def explore_forum(page: Page) -> list[dict]:
    """Extract post list from the forum page."""
    print("\n--- 探索论坛页面 ---")

    # Take screenshot of forum list
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    page.screenshot(path=str(SCREENSHOTS_DIR / f"forum_list_{ts}.png"), full_page=False)
    print(f"✓ 截图已保存: forum_list_{ts}.png")

    # Wait for content to load
    page.wait_for_timeout(3000)

    # Try to extract posts - multiple selector strategies for Vue SPA
    posts = []
    selectors = [
        "div.post-item", "div.article-item", "div.forum-item",
        "div.list-item", "a.post-link", "div.card",
        "[class*='post']", "[class*='article']", "[class*='item']",
    ]

    for selector in selectors:
        elements = page.query_selector_all(selector)
        if elements:
            print(f"✓ 找到 {len(elements)} 个元素 (selector: {selector})")
            for i, el in enumerate(elements[:20]):  # Limit to first 20
                text = el.inner_text().strip()
                href = el.get_attribute("href") or ""
                if text:
                    posts.append({
                        "index": i,
                        "selector": selector,
                        "text": text[:500],
                        "href": href,
                    })
            break

    if not posts:
        # Fallback: dump all visible text blocks for analysis
        print("未找到明确的帖子元素，抓取页面文本结构...")
        body_text = page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        posts = [{"index": i, "text": line[:300], "selector": "body-text"} for i, line in enumerate(lines[:50])]
        print(f"  提取了 {len(posts)} 行文本")

    # Print preview
    print(f"\n前 5 条内容预览：")
    for post in posts[:5]:
        preview = post["text"][:100].replace("\n", " ")
        print(f"  [{post['index']}] {preview}")

    return posts


def explore_post_detail(page: Page, posts: list[dict]) -> dict | None:
    """Try to navigate into a post detail page."""
    print("\n--- 探索帖子详情 ---")

    # Find a clickable post
    clickable = None
    for post in posts:
        href = post.get("href", "")
        if href and href != "#":
            clickable = post
            break

    if not clickable:
        # Try clicking the first post element directly
        selectors_to_try = [
            "[class*='post'] a", "[class*='article'] a", "[class*='item'] a",
            "a[href*='detail']", "a[href*='article']", "a[href*='post']",
        ]
        for selector in selectors_to_try:
            elements = page.query_selector_all(selector)
            if elements:
                print(f"尝试点击: {selector}")
                elements[0].click()
                page.wait_for_timeout(3000)
                break
        else:
            print("未找到可点击的帖子链接")
            return None
    else:
        href = clickable["href"]
        if not href.startswith("http"):
            href = f"https://research.meritco-group.com{href}"
        print(f"导航到: {href}")
        page.goto(href, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

    # Screenshot detail page
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    page.screenshot(path=str(SCREENSHOTS_DIR / f"post_detail_{ts}.png"), full_page=True)
    print(f"✓ 详情页截图: post_detail_{ts}.png")

    # Extract content
    detail = {
        "url": page.url,
        "title": page.title(),
        "content_preview": page.inner_text("body")[:2000],
    }
    print(f"  标题: {detail['title']}")
    print(f"  URL: {detail['url']}")
    print(f"  内容前 200 字: {detail['content_preview'][:200]}")

    return detail


def save_results(api_log: list[dict], posts: list[dict], detail: dict | None):
    """Save all captured data to JSON files."""
    if api_log:
        api_path = DATA_DIR / "api_log.json"
        api_path.write_text(json.dumps(api_log, ensure_ascii=False, indent=2))
        print(f"\n✓ API 日志已保存: {api_path} ({len(api_log)} 条)")

    if posts:
        posts_path = DATA_DIR / "posts.json"
        posts_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2))
        print(f"✓ 帖子列表已保存: {posts_path} ({len(posts)} 条)")

    if detail:
        detail_path = DATA_DIR / "post_detail.json"
        detail_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2))
        print(f"✓ 帖子详情已保存: {detail_path}")


def main():
    parser = argparse.ArgumentParser(description="Meritco 论坛探索脚本")
    parser.add_argument("--visible", action="store_true", help="强制 visible 模式（跳过 headless 尝试）")
    args = parser.parse_args()

    setup_dirs()

    # 1. Login
    p, context, page = login(force_visible=args.visible)

    try:
        # 2. Set up API interception
        print("\n开始拦截 API 请求...")
        api_log = intercept_api(page)

        # Ensure we're on the forum page
        if "forum" not in page.url:
            print(f"当前页面: {page.url}，导航到论坛...")
            page.goto(FORUM_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

        # 3. Explore forum list
        posts = explore_forum(page)

        # 4. Explore a post detail
        detail = explore_post_detail(page, posts)

        # 5. Save results
        save_results(api_log, posts, detail)

        print("\n" + "=" * 60)
        print("探索完成！检查以下文件：")
        print(f"  截图: {SCREENSHOTS_DIR}/")
        print(f"  API 日志: {DATA_DIR}/api_log.json")
        print(f"  帖子列表: {DATA_DIR}/posts.json")
        if detail:
            print(f"  帖子详情: {DATA_DIR}/post_detail.json")
        print("=" * 60)

    finally:
        context.close()
        p.stop()


if __name__ == "__main__":
    main()
