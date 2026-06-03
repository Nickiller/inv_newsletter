"""Probe candidate PDF download endpoints for Meritco.

The detail response gives us:
  pdfUrl: [{ "url": "<base64-RSA-encrypted file id>", "name": "...", ... }]

We need to find the API endpoint that decrypts this and serves the PDF.
"""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import (  # noqa: E402
    _get_token,
    _sign,
    _common_headers,
    BASE_URL,
    API_BASE,
)


# Use 3076 (260413 周报)
FORUM_ID = 3076
PDF_URL_BLOB = "c55WBMhj2h+eEYQQ4WcL+KeVDEjBxoqHGPT1CbjNW0GdIw1fhxgsFo2tR8jye0O1TRUsVBoeGz6qItu4l6XaBygMNkUpHFBnoVXej0+owS0xmyqMFijciFPYg0dwYcf8iumf9WiIAUqFHm4sP0C4Q0i6Uh/noQTz5WzFi4et0Is="
PDF_NAME = "260413 久谦论坛-调研周报.pdf"


# Endpoint × method × payload combinations to try
ENDPOINTS = [
    f"{API_BASE}/file/download",
    f"{API_BASE}/forum/file/download",
    f"{API_BASE}/forum/file/get",
    f"{API_BASE}/file/get",
    f"{API_BASE}/file/preview",
    f"{API_BASE}/forum/file/preview",
    f"{API_BASE}/file/url",
    f"{API_BASE}/forum/file/url",
    f"{API_BASE}/forum/file/getFileUrl",
    f"{API_BASE}/forum/file/getDownloadUrl",
    f"{API_BASE}/forum/file/getPreviewUrl",
    f"{API_BASE}/file/getFileUrl",
    f"{API_BASE}/file/getDownloadUrl",
    f"{API_BASE}/file/getPreviewUrl",
    f"{API_BASE}/forum/select/file",
    f"{API_BASE}/forum/select/pdf",
    f"{API_BASE}/forum/select/download",
]

PAYLOADS = [
    {"url": PDF_URL_BLOB},
    {"url": PDF_URL_BLOB, "forumId": FORUM_ID},
    {"fileUrl": PDF_URL_BLOB},
    {"pdfUrl": PDF_URL_BLOB},
    {"forumId": FORUM_ID, "fileUrl": PDF_URL_BLOB},
    {"forumId": FORUM_ID, "url": PDF_URL_BLOB, "name": PDF_NAME},
]


def make_headers(token: str, sign_input: str) -> dict:
    h = _common_headers(token)
    h["x-my-header"] = _sign(sign_input)
    h["x-forum-header"] = _sign(sign_input)  # also try same
    return h


def probe(endpoint: str, method: str, payload: dict, token: str, sign_input: str):
    headers = make_headers(token, sign_input)
    try:
        if method == "GET":
            params = payload
            r = requests.get(endpoint, headers=headers, params=params, timeout=15)
        else:
            r = requests.post(
                endpoint,
                headers=headers,
                cookies={"X-User-Type": "default"},
                json=payload,
                timeout=15,
            )
    except Exception as e:
        return None, f"EXCEPTION: {e}"

    ct = r.headers.get("content-type", "")
    cl = r.headers.get("content-length", "?")

    info = f"status={r.status_code} ct={ct} len={cl}"
    if r.status_code == 404:
        return None, info
    if r.status_code == 401:
        return r, info + " AUTH"
    if "json" in ct:
        try:
            j = r.json()
            preview = json.dumps(j, ensure_ascii=False)[:300]
            info += f" body={preview}"
        except Exception:
            info += f" body={r.text[:200]}"
    elif "pdf" in ct.lower():
        info += " ★PDF★"
        return r, info
    elif r.status_code == 200:
        info += f" body={r.content[:80]!r}"
    else:
        info += f" body={r.text[:120]}"

    return r, info


def main():
    token = _get_token()

    # Try several sign inputs (the formula likely follows the same pattern as detail)
    SIGN_VARIANTS = [
        ("token+forumId", token + str(FORUM_ID)),
        ("token+url", token + PDF_URL_BLOB),
        ("token+forumId+url", token + str(FORUM_ID) + PDF_URL_BLOB),
        ("token only", token),
    ]

    print(f"Probing {len(ENDPOINTS)} endpoints × {len(PAYLOADS)} payloads × {len(SIGN_VARIANTS)} sign-variants\n")

    found = []
    for endpoint in ENDPOINTS:
        for sign_label, sign_input in SIGN_VARIANTS:
            for method in ["POST"]:  # GET first round skipped to reduce noise
                for payload in PAYLOADS:
                    r, info = probe(endpoint, method, payload, token, sign_input)
                    # Only print interesting results (not 404)
                    if r is None and "404" in (info or ""):
                        continue
                    short_ep = endpoint.replace(API_BASE, "")
                    print(f"{method:4} {short_ep:40} sign={sign_label:25} payload_keys={list(payload.keys())}")
                    print(f"     → {info[:250]}")
                    if r is not None and r.status_code == 200 and "pdf" in info.lower():
                        found.append((endpoint, method, payload, sign_input))
                        break
                if found and "pdf" in (info or "").lower():
                    break
            if found:
                break
        if found:
            break

    if found:
        print(f"\n★ FOUND PDF endpoint: {found[0]}")
    else:
        print("\nNo direct PDF response. Look at non-404 responses above for hints.")


if __name__ == "__main__":
    main()
