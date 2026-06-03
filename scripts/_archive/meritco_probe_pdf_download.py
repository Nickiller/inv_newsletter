"""Open one article page in Playwright and capture PDF-related network calls.

Goal: discover the actual API endpoint used to download PDF files from Meritco.
"""

import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Response

BROWSER_STATE_DIR = Path(".browser_state_meritco")
TARGET_FORUM_ID = 3076  # 260413 周报 (has PDF attachment)
BASE_URL = "https://research.meritco-group.com"


URL_CANDIDATES = [
    f"{BASE_URL}/forumDetail?forumId={TARGET_FORUM_ID}",
    f"{BASE_URL}/forum/detail/{TARGET_FORUM_ID}?forumType=3",
    f"{BASE_URL}/forum/detail?id={TARGET_FORUM_ID}&forumType=3",
    f"{BASE_URL}/forumDetail?forumId={TARGET_FORUM_ID}&type=3",
    f"{BASE_URL}/research/{TARGET_FORUM_ID}",
]


def main():
    captured: list[dict] = []

    def on_response(resp: Response):
        url = resp.url
        path = urlparse(url).path
        ct = resp.headers.get("content-type", "")
        # Capture anything PDF-related or interesting
        if any(kw in url.lower() for kw in ["pdf", "file", "download", "attach"]):
            entry = {
                "method": resp.request.method,
                "url": url,
                "status": resp.status,
                "content_type": ct,
                "content_length": resp.headers.get("content-length", "?"),
            }
            try:
                if "json" in ct:
                    entry["body"] = resp.json()
            except Exception:
                pass
            captured.append(entry)
            print(f"  >> {resp.request.method} {path} → {resp.status} ({ct})")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_STATE_DIR),
            headless=False,  # visible so we can see what happens
            channel="chrome",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)

        # Try URL candidates
        for url in URL_CANDIDATES:
            print(f"\nTrying URL: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            current = page.url
            title = page.title()
            print(f"  landed on: {current}")
            print(f"  page title: {title}")
            # Check if we're on the actual article (look for the title text)
            content = page.content()
            if "久谦论坛-调研周报" in content or "260413" in content:
                print("  ✓ Looks like the right page!")
                break
            else:
                print("  ✗ Doesn't look right (no article title in content)")

        # Now look for PDF download buttons
        print("\nLooking for PDF download elements...")
        page.wait_for_timeout(2000)
        candidates = page.evaluate("""() => {
            const out = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const text = (el.innerText || '').trim();
                if (!text || text.length > 100) continue;
                if (/(下载|download|\\.pdf|pdf)/i.test(text)) {
                    out.push({
                        tag: el.tagName,
                        text: text.substring(0, 80),
                        classes: (el.className || '').toString().substring(0, 80),
                    });
                }
                if (out.length >= 30) break;
            }
            return out;
        }""")
        print(f"  found {len(candidates)} elements containing PDF/download text:")
        for c in candidates[:15]:
            print(f"    <{c['tag']}> '{c['text']}' class='{c['classes']}'")

        # Try clicking elements that look like download buttons
        for c in candidates:
            if "下载" in c["text"] or ".pdf" in c["text"].lower():
                print(f"\n  trying to click: {c['text']}")
                try:
                    page.get_by_text(c["text"]).first.click(timeout=3000)
                    page.wait_for_timeout(4000)
                    print("  click ok")
                    break
                except Exception as e:
                    print(f"  click failed: {e}")

        # Also try keyboard interaction in case there's a hidden link
        page.wait_for_timeout(3000)

        print("\n--- captured network calls ---")
        for c in captured:
            print(json.dumps(c, ensure_ascii=False, indent=2)[:500])

        # Save full captures
        out = Path("data/meritco_dci_probe/pdf_network_capture.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
        print(f"\nFull capture saved: {out}")

        # Keep browser open briefly to let user observe
        print("\n(browser will close in 15s — observe what happened)")
        page.wait_for_timeout(15000)
        ctx.close()


if __name__ == "__main__":
    main()
