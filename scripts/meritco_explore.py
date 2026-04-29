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

from playwright.sync_api import sync_playwright, Page, Response

BROWSER_STATE_DIR = Path(".browser_state_meritco")
DATA_DIR = Path("data/meritco")
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
BASE_URL = "https://research.meritco-group.com"
FORUM_URL = f"{BASE_URL}/forum?forumType=3"
MINUTES_URL = f"{BASE_URL}/forum?forumType=2"


def setup_dirs():
    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def is_logged_in(page: Page) -> bool:
    """Check if we're logged in by looking for login/scan-code indicators."""
    page.wait_for_timeout(3000)
    url = page.url
    if "login" in url.lower() or "auth" in url.lower():
        return False
    content = page.content().lower()
    if "扫码" in content or "微信登录" in content or "scan" in content:
        if "forum" not in url:
            return False
    return True


def launch_browser(headless: bool) -> tuple:
    """Launch persistent browser context."""
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
        page.wait_for_timeout(5000)

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

    start = time.time()
    while (time.time() - start) < 120:
        page.wait_for_timeout(3000)
        if is_logged_in(page):
            print("✓ 登录成功！")
            page.wait_for_timeout(3000)
            return p, context, page

    raise RuntimeError("登录超时（120 秒），请重试。")


class APICapture:
    """Intercept and capture API responses."""

    def __init__(self, page: Page):
        self.page = page
        self.api_log: list[dict] = []
        self._forum_list: list[dict] = []
        self._detail_data: dict | None = None
        page.on("response", self._handle_response)

    def _handle_response(self, response: Response):
        url = response.url
        parsed = urlparse(url)
        content_type = response.headers.get("content-type", "")

        # Skip non-JSON
        if "json" not in content_type:
            return

        try:
            body = response.json()
        except Exception:
            return

        path = parsed.path

        # Capture forum list
        if "forum/select/list" in path:
            result = body.get("result", {})
            self._forum_list = result.get("forumList", [])
            total = result.get("total", 0)
            print(f"  API 纪要列表: {len(self._forum_list)} 条 (总计 {total})")

        # Capture detail content — full response, not truncated
        if "forum/select/id" in path:
            self._detail_data = body.get("result", body)
            content = ""
            if isinstance(self._detail_data, dict):
                content = self._detail_data.get("content", "") or ""
            print(f"  API 纪要详情: captured ({len(content)} 字 content)")

        # Log all API calls
        self.api_log.append({
            "timestamp": datetime.now().isoformat(),
            "method": response.request.method,
            "path": path,
            "status": response.status,
        })
        print(f"  API: {response.request.method} {path} → {response.status}")

    @property
    def forum_list(self) -> list[dict]:
        return self._forum_list

    @property
    def detail_data(self) -> dict | None:
        return self._detail_data


def fetch_minutes_list(page: Page, capture: APICapture) -> list[dict]:
    """Navigate to 纪要 page and capture the API response."""
    print("\n--- 获取纪要列表 ---")
    page.goto(MINUTES_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    # Screenshot
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    page.screenshot(path=str(SCREENSHOTS_DIR / f"minutes_list_{ts}.png"), full_page=False)
    print(f"✓ 截图: minutes_list_{ts}.png")

    posts = capture.forum_list
    if posts:
        print(f"\n前 5 条纪要：")
        for i, post in enumerate(posts[:5]):
            title = post.get("title", "")[:80]
            date = post.get("meetingTime", "")[:10]
            print(f"  [{i}] {date} | {title}")
    else:
        print("⚠ 未通过 API 捕获到纪要列表")

    return posts


def fetch_first_detail(page: Page, capture: APICapture, posts: list[dict]) -> dict | None:
    """Navigate to the first post's detail page and capture content."""
    print("\n--- 提取第一篇纪要详情 ---")

    if not posts:
        print("无纪要可提取")
        return None

    first = posts[0]
    post_id = first.get("id")
    title = first.get("title", "")[:80]
    print(f"目标: [{post_id}] {title}")

    # Try navigating to detail page — common Vue SPA patterns
    detail_urls = [
        f"{BASE_URL}/forum/detail/{post_id}?forumType=2",
        f"{BASE_URL}/forum/{post_id}?forumType=2",
        f"{BASE_URL}/forum/detail?id={post_id}&forumType=2",
    ]

    # Dump HTML structure of the first visible post for debugging
    print("分析页面 DOM 结构...")
    first_item_html = page.evaluate("""() => {
        // Find elements that contain the post title text
        const items = document.querySelectorAll('[class*="item"], [class*="card"], [class*="post"], [class*="article"]');
        const results = [];
        for (const item of items) {
            const text = item.innerText || '';
            if (text.length > 100 && text.length < 5000) {
                results.push({
                    tag: item.tagName,
                    classes: item.className,
                    outerHTMLpreview: item.outerHTML.substring(0, 500),
                    links: Array.from(item.querySelectorAll('a[href]')).map(a => ({
                        href: a.href,
                        text: (a.innerText || '').substring(0, 50)
                    }))
                });
            }
            if (results.length >= 3) break;
        }
        return results;
    }""")
    print(f"  DOM 分析结果: {len(first_item_html)} 个候选元素")
    for i, item in enumerate(first_item_html):
        print(f"  [{i}] <{item['tag']}> class=\"{item['classes'][:80]}\"")
        print(f"      HTML: {item['outerHTMLpreview'][:200]}")
        for link in item.get("links", []):
            print(f"      链接: {link['href'][:80]} | {link['text']}")

    # Try clicking the first post title link
    clicked = False
    # Strategy 1: find <a> tags that link to post detail
    links = page.evaluate("""() => {
        const allLinks = document.querySelectorAll('a[href]');
        return Array.from(allLinks)
            .filter(a => a.href && a.innerText.length > 20)
            .slice(0, 20)
            .map(a => ({href: a.href, text: (a.innerText || '').substring(0, 80)}));
    }""")
    print(f"\n  页面上的链接 ({len(links)} 条):")
    for link in links[:10]:
        print(f"    {link['href'][:80]} | {link['text'][:50]}")

    # Strategy 2: click on the title text directly
    expert_info = first.get("expertInformation", "")
    if expert_info:
        print(f"\n尝试点击包含「{expert_info}」的元素...")
        el = page.query_selector(f"text={expert_info}")
        if el:
            el.click()
            page.wait_for_timeout(5000)
            clicked = True
            print(f"  点击成功，当前 URL: {page.url}")

    if not clicked:
        # Strategy 3: try URL patterns
        for url in detail_urls:
            print(f"尝试 URL: {url}")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if page.url != MINUTES_URL and "forum" in page.url:
                break

    # Screenshot
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    page.screenshot(path=str(SCREENSHOTS_DIR / f"detail_{ts}.png"), full_page=True)
    print(f"✓ 详情页截图: detail_{ts}.png")
    print(f"  当前 URL: {page.url}")

    # Build detail from API capture
    detail = {
        "url": page.url,
        "metadata": {
            "id": first.get("id"),
            "title": first.get("title"),
            "summary": first.get("summary"),
            "expert": first.get("expertInformation"),
            "industry": first.get("industry"),
            "meeting_time": first.get("meetingTime"),
            "author": first.get("author"),
            "related_targets": first.get("relatedTargets"),
            "language": "中文" if first.get("language") == 1 else "英文",
        },
        "api_data": capture.detail_data,
    }

    # Extract content from API response
    api_content = ""
    if capture.detail_data and isinstance(capture.detail_data, dict):
        api_content = capture.detail_data.get("content", "") or ""
        # content is likely HTML — also grab contentTextShow if available
        text_content = capture.detail_data.get("contentTextShow", "") or ""
        detail["content_html"] = api_content
        detail["content_text"] = text_content
        print(f"✓ API content: {len(api_content)} 字 HTML, {len(text_content)} 字 text")
    else:
        print("⚠ 未通过 API 捕获到纪要内容")

    # Print preview
    preview = detail.get("content_text") or api_content
    if preview:
        # Strip HTML tags for preview
        import re
        clean = re.sub(r'<[^>]+>', '', preview)[:800]
        print(f"\n  内容预览:\n{'─' * 40}")
        print(clean)
        print(f"{'─' * 40}")

    return detail


def save_results(api_log: list[dict], posts: list[dict], detail: dict | None):
    """Save all captured data to JSON files."""
    if api_log:
        path = DATA_DIR / "api_log.json"
        path.write_text(json.dumps(api_log, ensure_ascii=False, indent=2))
        print(f"\n✓ API 日志: {path} ({len(api_log)} 条)")

    if posts:
        path = DATA_DIR / "posts.json"
        path.write_text(json.dumps(posts, ensure_ascii=False, indent=2))
        print(f"✓ 纪要列表: {path} ({len(posts)} 条)")

    if detail:
        path = DATA_DIR / "post_detail.json"
        path.write_text(json.dumps(detail, ensure_ascii=False, indent=2))
        print(f"✓ 纪要详情: {path}")


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
        capture = APICapture(page)

        # 3. Fetch 纪要 list (via API interception)
        posts = fetch_minutes_list(page, capture)

        # 4. Navigate to first post detail
        detail = fetch_first_detail(page, capture, posts)

        # 5. Save results
        save_results(capture.api_log, posts, detail)

        print("\n" + "=" * 60)
        print("探索完成！")
        print(f"  截图: {SCREENSHOTS_DIR}/")
        print(f"  API 日志: {DATA_DIR}/api_log.json")
        print(f"  纪要列表: {DATA_DIR}/posts.json")
        if detail:
            print(f"  纪要详情: {DATA_DIR}/post_detail.json")
        print("=" * 60)

    finally:
        context.close()
        p.stop()


if __name__ == "__main__":
    main()
