"""Test the discovered /forum/pdfDownloadWatermark endpoint."""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import (  # noqa: E402
    _get_token, _sign, _common_headers, API_BASE,
)

FORUM_ID = 3076
PDF_URL_BLOB = "c55WBMhj2h+eEYQQ4WcL+KeVDEjBxoqHGPT1CbjNW0GdIw1fhxgsFo2tR8jye0O1TRUsVBoeGz6qItu4l6XaBygMNkUpHFBnoVXej0+owS0xmyqMFijciFPYg0dwYcf8iumf9WiIAUqFHm4sP0C4Q0i6Uh/noQTz5WzFi4et0Is="

ENDPOINT = f"{API_BASE}/forum/pdfDownloadWatermark"


def call(method: str, payload: dict, sign_input: str, label: str):
    h = _common_headers(_get_token())
    h["x-my-header"] = _sign(sign_input)
    h["x-forum-header"] = _sign(sign_input)

    if method == "GET":
        r = requests.get(ENDPOINT, headers=h, params=payload, timeout=30)
    else:
        r = requests.post(
            ENDPOINT, headers=h, json=payload,
            cookies={"X-User-Type": "default"}, timeout=30,
        )
    ct = r.headers.get("content-type", "")
    cl = len(r.content)
    print(f"[{label:30}] {method} status={r.status_code} ct={ct} len={cl}")
    if "json" in ct:
        try:
            print(f"    body: {r.json()}")
        except Exception:
            print(f"    text: {r.text[:300]}")
    elif "pdf" in ct.lower() or r.content[:4] == b"%PDF":
        out = Path(f"/tmp/meritco_pdf_test_{label}.pdf")
        out.write_bytes(r.content)
        print(f"    ★ PDF saved → {out} ({cl} bytes)")
    elif r.status_code == 200:
        print(f"    bytes[:80]: {r.content[:80]!r}")
    else:
        print(f"    text: {r.text[:200]}")


def main():
    token = _get_token()
    sign_inputs = [
        ("token+forumId", token + str(FORUM_ID)),
        ("token+url", token + PDF_URL_BLOB),
        ("token+forumId+url", token + str(FORUM_ID) + PDF_URL_BLOB),
        ("token only", token),
        ("forumId only", str(FORUM_ID)),
    ]
    payloads = [
        {"forumId": FORUM_ID},
        {"url": PDF_URL_BLOB},
        {"forumId": FORUM_ID, "url": PDF_URL_BLOB},
        {"fileUrl": PDF_URL_BLOB, "forumId": FORUM_ID},
    ]
    for method in ["POST", "GET"]:
        for s_label, s_input in sign_inputs:
            for i, payload in enumerate(payloads):
                call(method, payload, s_input, f"{method[:1]}_{s_label[:8]}_{i}")


if __name__ == "__main__":
    main()
