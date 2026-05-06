"""Manual-assisted PDF download capture.

Opens a visible browser at the Meritco forum (logged in via persistent
browser_state). User manually:
  1. Navigates to a research article (forumType=3)
  2. Opens the PDF
  3. Clicks 下载

The script captures every XHR/fetch and saves it. Press Ctrl+C when done.
"""

import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BROWSER_STATE_DIR = Path(".browser_state_meritco")
START_URL = "https://research.meritco-group.com/forum?forumType=3"
CAPTURE_FILE = Path("data/meritco_dci_probe/manual_pdf_capture.json")
CAPTURE_FILE.parent.mkdir(parents=True, exist_ok=True)


def main():
    captured: list[dict] = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_STATE_DIR),
            headless=False,
            channel="chrome",
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_request(req):
            url = req.url
            rt = req.resource_type
            if rt in ("xhr", "fetch"):
                entry = {
                    "method": req.method,
                    "url": url,
                    "headers": dict(req.headers),
                }
                try:
                    if req.post_data:
                        entry["post_data"] = req.post_data
                except Exception:
                    pass
                captured.append(entry)
                print(f"  {req.method} {urlparse(url).path}")
                if req.post_data:
                    print(f"     payload: {req.post_data[:300]}")

        def on_download(d):
            print(f"\n★ DOWNLOAD: {d.suggested_filename}")
            print(f"  url: {d.url}")
            sp = Path("data/meritco_dci") / d.suggested_filename
            d.save_as(str(sp))
            print(f"  saved → {sp} ({sp.stat().st_size} bytes)")
            captured.append({
                "_download": True,
                "filename": d.suggested_filename,
                "url": d.url,
                "saved_to": str(sp),
            })

        page.on("request", on_request)
        page.on("download", on_download)

        page.goto(START_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        if "login" in page.url.lower():
            print("Need to log in. Please scan QR code...")
            deadline = time.time() + 180
            while time.time() < deadline:
                time.sleep(2)
                if "login" not in page.url.lower():
                    print("Logged in.")
                    break

        print()
        print("=" * 70)
        print("浏览器已打开在「研究」板块。请操作：")
        print("  1. 找到 ID 3076 的文章 (260413 久谦论坛-调研周报) — 应该在第一页")
        print("  2. 点开文章 → 出现 PDF 预览")
        print("  3. 点工具栏「下载」按钮")
        print("  4. 等下载触发后，回到这里按 Ctrl+C 停止脚本")
        print("=" * 70)
        print()
        print("正在捕获 XHR/fetch 请求...")
        print()

        try:
            while True:
                time.sleep(2)
                CAPTURE_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            pass
        finally:
            CAPTURE_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
            print(f"\n保存了 {len(captured)} 条网络记录 → {CAPTURE_FILE}")
            ctx.close()


if __name__ == "__main__":
    main()
