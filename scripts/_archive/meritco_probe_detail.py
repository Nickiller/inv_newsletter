"""Probe detail responses for the 7 DCI items to understand attachment structure."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import _get_token, _post_signed, API_BASE


IDS = [3118, 2943, 3125, 3076, 3044]


def fetch_detail_raw(token: str, forum_id: int) -> dict:
    body = {"platform": "RESEARCH_PC"}
    my_input = token + str(forum_id)
    forum_input = token + "  " + str(forum_id)
    url = f"{API_BASE}/forum/select/id?forumId={forum_id}"
    return _post_signed(url, token, body, my_input, forum_input)


def main():
    token = _get_token()

    for fid in IDS:
        print(f"\n{'=' * 80}\nForum {fid}")
        print("=" * 80)
        try:
            resp = fetch_detail_raw(token, fid)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if resp.get("code") != 200:
            print(f"  API code={resp.get('code')} message={resp.get('message')}")
            continue

        result = resp.get("result") or {}
        keys = list(result.keys())
        print(f"  result keys ({len(keys)}): {keys}")

        # Look for PDF / attachment related fields
        for k in keys:
            v = result.get(k)
            if v is None or v == "" or v == [] or v == {}:
                continue
            kl = k.lower()
            if any(x in kl for x in ["pdf", "url", "file", "attach", "annex", "doc"]):
                print(f"  >> {k}: {repr(v)[:300]}")

        # Print content type/length
        content = result.get("content") or ""
        ct = result.get("contentTextShow") or ""
        report_type = result.get("reportType")
        report_type_name = result.get("reportTypeName")
        print(f"  reportType={report_type} reportTypeName={report_type_name}")
        print(f"  content length={len(content)}, contentTextShow length={len(ct)}")

        # Print a tiny content snippet to gauge format
        if content:
            print(f"  content[:200]: {content[:200]!r}")

        # Save full response for inspection
        out = Path(f"data/meritco_dci_probe/{fid}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(resp, ensure_ascii=False, indent=2))
        print(f"  saved: {out}")


if __name__ == "__main__":
    main()
