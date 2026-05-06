"""Download Meritco research PDFs via /forum/pdfDownloadWatermark endpoint.

Endpoint discovered via DevTools network capture:
  POST /matrix-search/forum/pdfDownloadWatermark
  Headers: token (no RSA signing needed for this endpoint)
  Body: {"pdfOSSUrlEncoded": "<base64-RSA-encrypted oss url from pdfUrl[].url>"}
  Returns: PDF binary (with watermark applied server-side)
"""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import _get_token, _post_signed, API_BASE  # noqa: E402


PDF_ENDPOINT = f"{API_BASE}/forum/pdfDownloadWatermark"
OUT_DIR = Path("data/meritco_dci")
IDS = [3076, 3125, 3044]


def fetch_detail(token: str, forum_id: int) -> dict:
    body = {"platform": "RESEARCH_PC"}
    my_input = token + str(forum_id)
    forum_input = token + "  " + str(forum_id)
    url = f"{API_BASE}/forum/select/id?forumId={forum_id}"
    resp = _post_signed(url, token, body, my_input, forum_input)
    if resp.get("code") != 200:
        raise RuntimeError(f"detail fetch failed for {forum_id}: {resp}")
    return resp.get("result") or {}


def download_pdf(token: str, oss_url_encoded: str, save_path: Path) -> int:
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://research.meritco-group.com",
        "referer": "https://research.meritco-group.com/",
        "token": token,
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
    }
    payload = {"pdfOSSUrlEncoded": oss_url_encoded}
    r = requests.post(
        PDF_ENDPOINT,
        headers=headers,
        cookies={"X-User-Type": "default"},
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if "pdf" not in ct.lower() and r.content[:4] != b"%PDF":
        # Maybe JSON error
        try:
            err = r.json()
            raise RuntimeError(f"non-PDF response (ct={ct}): {err}")
        except ValueError:
            raise RuntimeError(f"non-PDF response (ct={ct}): {r.content[:200]!r}")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(r.content)
    return len(r.content)


def main():
    token = _get_token()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for fid in IDS:
        print(f"\n=== Forum {fid} ===")
        try:
            item = fetch_detail(token, fid)
        except Exception as e:
            print(f"  detail error: {e}")
            continue

        meeting_time = (item.get("meetingTime") or "")[:10]
        yymmdd = meeting_time.replace("-", "")[2:] if meeting_time else "unknown"
        title = item.get("title", "untitled")

        # pdfUrl is a JSON-encoded string of an array of file objects
        pdf_url_raw = item.get("pdfUrl") or "[]"
        try:
            pdf_files = json.loads(pdf_url_raw) if isinstance(pdf_url_raw, str) else pdf_url_raw
        except Exception as e:
            print(f"  pdfUrl parse error: {e} (raw={pdf_url_raw[:100]!r})")
            continue

        if not pdf_files:
            print(f"  no PDF attachments")
            continue

        print(f"  date={meeting_time} title={title[:60]}")
        print(f"  {len(pdf_files)} PDF attachment(s):")

        for pdf in pdf_files:
            name = pdf.get("name", f"forum-{fid}.pdf")
            size_announced = pdf.get("size", "?")
            oss_url = pdf.get("url", "")
            if not oss_url:
                print(f"    [{name}] no url field, skip")
                continue

            # Save filename: YYMMDD_{forumId}_{originalName}
            safe_name = name.replace("/", "_").replace("\\", "_")
            save_path = OUT_DIR / f"{yymmdd}_{fid}_{safe_name}"

            print(f"    downloading [{name}] (announced {size_announced} bytes)...")
            try:
                got = download_pdf(token, oss_url, save_path)
                print(f"    ✓ saved → {save_path.name} ({got} bytes)")
            except Exception as e:
                print(f"    ✗ download failed: {e}")


if __name__ == "__main__":
    main()
