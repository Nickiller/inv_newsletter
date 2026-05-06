"""Open a Meritco research article in a visible browser, wait for user to
log in if needed, then capture the actual PDF download network call.

Run interactively:  uv run scripts/meritco_capture_pdf_call.py
After you log in (扫码) and click the PDF download in the article view, the
captured network call (URL, method, payload, headers, response) will be saved
to data/meritco_dci_probe/pdf_capture.json.

Press Ctrl+C in terminal when done observing.
"""

import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BROWSER_STATE_DIR = Path(".browser_state_meritco")
TARGET_FORUM_ID = 3076
ENTRY_URL = f"https://research.meritco-group.com/report/auth?forumId={TARGET_FORUM_ID}"

CAPTURE_FILE = Path("data/meritco_dci_probe/pdf_capture.json")
CAPTURE_FILE.parent.mkdir(parents=True, exist_ok=True)


captured: list[dict] = []


def main():
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
            path = urlparse(url).path
            if any(kw in url.lower() for kw in ["pdf", "download", "watermark", "file/", "/file"]):
                entry = {
                    "phase": "request",
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
                print(f"  REQ  {req.method} {path}")

        def on_response(resp):
            url = resp.url
            path = urlparse(url).path
            ct = resp.headers.get("content-type", "")
            if any(kw in url.lower() for kw in ["pdf", "download", "watermark"]):
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
                print(f"  RESP {resp.status} {path} ({ct})")

        def on_download(download):
            print(f"\n★ DOWNLOAD: suggested_filename={download.suggested_filename}")
            print(f"  url: {download.url}")
            save_path = Path("data/meritco_dci") / download.suggested_filename
            save_path.parent.mkdir(parents=True, exist_ok=True)
            download.save_as(str(save_path))
            print(f"  saved → {save_path}")
            captured.append({
                "phase": "download_event",
                "suggested_filename": download.suggested_filename,
                "url": download.url,
                "saved_to": str(save_path),
            })

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("download", on_download)

        print(f"Navigating to {ENTRY_URL}")
        page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=30000)

        print()
        print("=" * 70)
        print("浏览器已打开。如果看到登录页，请扫码登录。")
        print("登录后页面会跳转到文章详情。请手动点击 PDF 下载按钮。")
        print("捕获到下载网络包后，按 Ctrl+C 退出。")
        print("=" * 70)
        print()

        try:
            # Loop forever, periodically save captures
            while True:
                time.sleep(3)
                if captured:
                    CAPTURE_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            pass
        finally:
            CAPTURE_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
            print(f"\nCaptured {len(captured)} entries → {CAPTURE_FILE}")
            ctx.close()


if __name__ == "__main__":
    main()
