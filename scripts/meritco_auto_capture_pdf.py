"""Automated PDF download capture — headless first, fallback to visible.

Strategy:
1. Open /report/auth?forumId=3076 in headless browser (re-uses BROWSER_STATE_DIR)
2. If it redirects to /login → SPA session cookies are dead, need user re-login
3. Otherwise: programmatically click the PDF download element + capture network
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BROWSER_STATE_DIR = Path(".browser_state_meritco")
TARGET_FORUM_ID = 3076
# /forumPDF is the SPA route for PDF viewing (found in app.js routes list)
ENTRY_URL = f"https://research.meritco-group.com/forumPDF?forumId={TARGET_FORUM_ID}&forumType=3"

CAPTURE_FILE = Path("data/meritco_dci_probe/pdf_capture_auto.json")
CAPTURE_FILE.parent.mkdir(parents=True, exist_ok=True)


def run(headless: bool):
    captured: list[dict] = []
    download_succeeded = False

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_STATE_DIR),
            headless=headless,
            channel="chrome",
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_request(req):
            url = req.url
            # Capture EVERYTHING except fonts/css/img to find PDF API
            rt = req.resource_type
            if rt not in ("font", "image", "stylesheet", "media") and "static/js" not in url:
                entry = {
                    "phase": "request",
                    "method": req.method,
                    "url": url,
                    "resource_type": rt,
                    "headers": dict(req.headers),
                }
                try:
                    if req.post_data:
                        entry["post_data"] = req.post_data
                except Exception:
                    pass
                captured.append(entry)
                print(f"  REQ  [{rt}] {req.method} {urlparse(url).path}")
                if req.post_data:
                    print(f"       payload: {req.post_data[:400]}")

        def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            rt = resp.request.resource_type
            if rt in ("xhr", "fetch") or "matrix-search" in url or "pdf" in url.lower():
                entry = {
                    "phase": "response",
                    "url": url,
                    "status": resp.status,
                    "content_type": ct,
                    "content_length": resp.headers.get("content-length", "?"),
                }
                try:
                    if "json" in ct:
                        entry["body_json"] = resp.json()
                except Exception:
                    pass
                captured.append(entry)
                print(f"  RESP {resp.status} {urlparse(url).path} ({ct})")

        def on_download(download):
            nonlocal download_succeeded
            print(f"\n★ DOWNLOAD event: {download.suggested_filename}")
            print(f"  url: {download.url}")
            save_path = Path("data/meritco_dci") / download.suggested_filename
            save_path.parent.mkdir(parents=True, exist_ok=True)
            download.save_as(str(save_path))
            print(f"  saved → {save_path} ({save_path.stat().st_size} bytes)")
            captured.append({
                "phase": "download_event",
                "suggested_filename": download.suggested_filename,
                "url": download.url,
                "saved_to": str(save_path),
            })
            download_succeeded = True

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("download", on_download)

        print(f"[{('headless' if headless else 'visible')}] Navigating to {ENTRY_URL}")
        try:
            page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  navigation error: {e}")

        page.wait_for_timeout(5000)
        landed = page.url
        print(f"  landed on: {landed}")

        if "login" in landed.lower():
            if headless:
                print("  → SPA logged out, can't proceed in headless mode")
                ctx.close()
                return False, captured
            # Visible mode: wait for user to scan QR code (poll URL until off /login)
            print("  → 请扫码登录，登录完成后脚本自动继续（最长等待 180 秒）")
            deadline = time.time() + 180
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                cur = page.url
                if "login" not in cur.lower():
                    print(f"  → 登录成功，当前 URL: {cur}")
                    break
            else:
                print("  → 登录等待超时")
                ctx.close()
                return False, captured
            # After login, navigate to article
            print(f"\n  navigating to article: {ENTRY_URL}")
            page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            landed = page.url
            print(f"  landed on: {landed}")

        # Page is the article — find PDF download trigger
        print("\nLooking for PDF download trigger...")
        page.wait_for_timeout(3000)

        # Strategy 1: look for elements with "下载" text or .pdf reference
        candidates = page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('*').forEach(el => {
                const text = (el.innerText || '').trim();
                if (!text || text.length > 60) return;
                if (/(下载|download|\\.pdf|查看|预览|附件)/i.test(text)) {
                    out.push({
                        tag: el.tagName,
                        text: text.substring(0, 60),
                        cls: (el.className || '').toString().substring(0, 60),
                        rect: el.getBoundingClientRect().top
                    });
                }
            });
            return out.slice(0, 30);
        }""")
        print(f"  found {len(candidates)} candidate elements:")
        for c in candidates[:15]:
            print(f"    <{c['tag']}> '{c['text']}' cls='{c['cls']}' top={c['rect']:.0f}")

        # Wait for loading mask to disappear
        print("\n  waiting for loading mask to clear...")
        try:
            page.wait_for_selector(".el-loading-mask", state="hidden", timeout=30000)
            print("  loading mask cleared")
        except Exception as e:
            print(f"  loading mask wait failed (may not exist): {e}")

        page.wait_for_timeout(2000)

        # Click the actual <button> 下载 in pdf-toolbar
        print("\n  clicking 下载 button in pdf-toolbar...")
        try:
            page.locator(".pdf-toolbar button:has-text('下载')").first.click(timeout=10000)
            print("  click ok")
            page.wait_for_timeout(10000)  # wait for download network call
        except Exception as e:
            print(f"  toolbar click failed: {e}")
            # Fallback: try any button with 下载
            try:
                page.locator("button:has-text('下载')").first.click(timeout=5000)
                print("  fallback click ok")
                page.wait_for_timeout(10000)
            except Exception as e2:
                print(f"  fallback click also failed: {e2}")

        # Save capture
        CAPTURE_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
        print(f"\nCaptured {len(captured)} entries → {CAPTURE_FILE}")

        if not headless:
            print("\nKeeping browser open 30s for manual interaction if needed...")
            page.wait_for_timeout(30000)

        ctx.close()
    return download_succeeded or len([c for c in captured if c.get("phase") == "request"]) > 0, captured


def main():
    # Headless mode often gets blocked on PDF viewers; go visible directly.
    print("=== Visible mode (session should be valid from prior login) ===")
    ok, cap = run(headless=False)
    if not ok:
        print("\n✗ Did not capture PDF download")
        sys.exit(1)


if __name__ == "__main__":
    main()
