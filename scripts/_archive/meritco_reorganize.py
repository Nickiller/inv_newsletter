"""Reorganize data/meritco_dci/ into thesis > notes > weekly subdirs with
clean filenames. Also re-download any missing PDFs.

Final layout:
  data/meritco_dci/
    01_thesis/    — Nokia/DCI thesis articles (most actionable views)
    02_notes/     — 纪要 / expert calls (raw conversations)
    03_weekly/    — 调研周报 (broadest, lowest density per word)
"""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import _get_token, _post_signed, API_BASE  # noqa: E402

ROOT = Path("data/meritco_dci")
PDF_ENDPOINT = f"{API_BASE}/forum/pdfDownloadWatermark"


# (forum_id, category_dir, slug) — slug becomes the filename's topic part
ITEMS = [
    # thesis (2)
    (3118, "01_thesis", "Nok_26Q1业绩"),
    (2943, "01_thesis", "Nokia_DCI业绩起点"),
    # notes (7) — DCI/expert minutes
    (2979, "02_notes", "德科立_DCI_1.6T"),
    (2995, "02_notes", "Google_CSP招标DCI_100亿"),
    (3017, "02_notes", "ATT_北美运营商资本开支"),
    (3062, "02_notes", "DCI_OCS_CSP调研"),
    (3105, "02_notes", "北美运营商DCI节奏II"),
    (3130, "02_notes", "北美DCI调研I"),
    (3078, "02_notes", "260413周报_纪要板块dup"),  # type=2 dup of 3076
    # weekly (3) — full reports with PDFs
    (3044, "03_weekly", "周报_科技周期制造"),
    (3076, "03_weekly", "周报"),
    (3125, "03_weekly", "Q1_hyperscaler"),
]


def fetch_detail(token: str, forum_id: int) -> dict:
    body = {"platform": "RESEARCH_PC"}
    my_input = token + str(forum_id)
    forum_input = token + "  " + str(forum_id)
    url = f"{API_BASE}/forum/select/id?forumId={forum_id}"
    resp = _post_signed(url, token, body, my_input, forum_input)
    return resp.get("result") or {}


def download_pdf(token: str, oss_url_encoded: str, save_path: Path) -> int:
    headers = {
        "accept": "application/json, text/plain, */*",
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
        PDF_ENDPOINT, headers=headers,
        cookies={"X-User-Type": "default"},
        json=payload, timeout=120,
    )
    r.raise_for_status()
    if r.content[:4] != b"%PDF":
        try:
            raise RuntimeError(f"non-PDF response: {r.json()}")
        except ValueError:
            raise RuntimeError(f"non-PDF response: {r.content[:200]!r}")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(r.content)
    # Verify
    actual = save_path.stat().st_size
    if actual != len(r.content):
        raise RuntimeError(f"size mismatch on disk: {actual} vs {len(r.content)}")
    return actual


def find_existing_md(forum_id: int) -> Path | None:
    """Find the existing .md file for this forum_id by reading frontmatter."""
    for md in ROOT.glob("*.md"):
        try:
            head = md.read_text(encoding="utf-8")[:512]
            if f'meritco-{forum_id}"' in head or f'meritco-{forum_id}\n' in head:
                return md
        except Exception:
            pass
    return None


def main():
    token = _get_token()

    for category in ["01_thesis", "02_notes", "03_weekly"]:
        (ROOT / category).mkdir(parents=True, exist_ok=True)

    moved_md = []
    saved_pdf = []

    for fid, category, slug in ITEMS:
        print(f"\n=== [{fid}] → {category}/  slug={slug} ===")

        # Move/rename markdown
        existing = find_existing_md(fid)
        if existing:
            # Preserve original date prefix from existing filename for consistency
            yymmdd = existing.name[:6] if existing.name[:6].isdigit() else "unknown"
            new_md = ROOT / category / f"{yymmdd}_{fid}_{slug}.md"
            if existing != new_md:
                if new_md.exists():
                    print(f"  ⚠ md already at target: {new_md.name}")
                else:
                    existing.rename(new_md)
                    print(f"  md: {existing.name[:50]}... → {new_md.name}")
                    moved_md.append(new_md)
        else:
            print(f"  ⚠ no existing md found for {fid}")

        # PDFs (only weekly category typically has them)
        if category != "03_weekly":
            continue

        item = fetch_detail(token, fid)
        pdf_files_raw = item.get("pdfUrl") or "[]"
        try:
            pdf_files = json.loads(pdf_files_raw) if isinstance(pdf_files_raw, str) else pdf_files_raw
        except Exception:
            pdf_files = []

        if not pdf_files:
            print(f"  no PDFs for {fid}")
            continue

        meeting_time = (item.get("meetingTime") or "")[:10]
        yymmdd = meeting_time.replace("-", "")[2:] if meeting_time else "unknown"

        for i, pdf in enumerate(pdf_files):
            oss_url = pdf.get("url")
            orig_name = pdf.get("name", f"file{i}.pdf")
            announced = pdf.get("size")
            if not oss_url:
                continue

            # Sanitize: ascii-only suffix from original name to avoid filesystem
            # weirdness with mixed CJK/symbols; embed index for multi-file forums.
            if len(pdf_files) == 1:
                target = ROOT / category / f"{yymmdd}_{fid}_{slug}.pdf"
            else:
                # Extract a short tag from original name
                tag = orig_name.replace(".pdf", "").split("_")[-1].replace(" ", "")[:20]
                tag = tag or f"part{i+1}"
                target = ROOT / category / f"{yymmdd}_{fid}_{slug}_{tag}.pdf"

            if target.exists() and target.stat().st_size > 100_000:
                print(f"  pdf [{i+1}/{len(pdf_files)}] {target.name} already exists ({target.stat().st_size}b), skip")
                saved_pdf.append(target)
                continue

            print(f"  pdf [{i+1}/{len(pdf_files)}] downloading [{orig_name}]...")
            try:
                got = download_pdf(token, oss_url, target)
                print(f"     ✓ {target.name} ({got} bytes, announced {announced})")
                saved_pdf.append(target)
            except Exception as e:
                print(f"     ✗ {e}")

    # Cleanup leftover stale PDFs at root level
    print("\n=== cleanup root-level legacy PDFs ===")
    for f in ROOT.glob("*.pdf"):
        print(f"  removing legacy: {f.name}")
        f.unlink()

    # Final inventory
    print("\n=== FINAL INVENTORY ===")
    for category in ["01_thesis", "02_notes", "03_weekly"]:
        d = ROOT / category
        files = sorted(d.iterdir())
        print(f"\n  {category}/ ({len(files)} files):")
        for f in files:
            size_kb = f.stat().st_size / 1024
            print(f"    {f.name}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
