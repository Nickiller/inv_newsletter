"""Clean up the DCI .md files for Feishu rendering and re-update existing docs.

Transformations:
  1. Strip YAML frontmatter; replace with a compact metadata blockquote.
  2. Drop the duplicated metadata block (原文链接/专家/相关标的/会议时间) — already in YAML.
  3. Detect wall-of-text paragraphs wrapped in `**...**` (whole-paragraph bold)
     - strip outer `**...**`
     - split on `****key****` markers; convert key segments to `> 💡 **关键**: ...` callouts
  4. Detect "XX观点：" / "市场聚焦的分支：" leading words → promote to `## H2`
  5. Detect "一、二、三、四" Chinese roman numeral bold lines → promote to `## H2`
  6. Drop the original H1 (title is shown by the Feishu doc itself).
  7. Q&A files (notes): keep Q/A structure intact, only clean YAML + dedup metadata.

Then push the cleaned content to each existing Feishu doc via `docs +update --mode replace_all`.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path("/Users/zhangxypro/Code/Claude_Workspace/inv_newsletter/data/meritco_dci")
LOG_PATH = ROOT / "_lark_upload_log.json"


# ---------- cleanup helpers ----------

YAML_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = YAML_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    body = text[m.end():]
    return meta, body


def build_meta_header(meta: dict) -> str:
    """Compact 1-2 line metadata header."""
    industry = meta.get("industry") or "—"
    received = (meta.get("received_at") or "")[:10]
    src_url = meta.get("source_url") or ""
    tickers = meta.get("tickers") or []
    sender = meta.get("sender_name") or ""
    expert = ""
    if "(" in sender and ")" in sender:
        expert = sender[sender.index("(") + 1 : sender.rindex(")")].strip()

    lines = []
    parts = [f"**行业**: {industry}", f"**日期**: {received}"]
    if expert:
        parts.append(f"**专家**: {expert}")
    lines.append("> " + " | ".join(parts))
    if tickers:
        lines.append("> **相关标的**: " + " · ".join(tickers))
    if src_url:
        lines.append(f"> **原文**: {src_url}")
    return "\n".join(lines)


def strip_dup_metadata(body: str) -> str:
    body = body.lstrip()
    # Remove the leading H1 (title) — Feishu doc has its own title
    body = re.sub(r"\A#\s+.+?\n+", "", body, count=1)
    # Remove all leading meta lines starting with **原文链接** / **专家** / **相关标的** /
    # **会议时间** — they're redundant with our header. Keep stripping until we hit
    # something that isn't one of these.
    meta_keys = ("原文链接", "专家", "相关标的", "会议时间", "行业", "分析师")
    while True:
        m = re.match(r"\A\s*\*\*([^*]+?)\*\*[:：]", body)
        if not m or not any(k in m.group(1) for k in meta_keys):
            break
        # consume to end of paragraph (blank line or single newline followed by non-meta)
        end = body.find("\n\n", m.end())
        if end == -1:
            body = ""
            break
        body = body[end + 2:]
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def extract_summary(body: str) -> tuple[str, str]:
    """Pull the > **摘要**: ... line out, return (summary_text, body_without_summary)."""
    m = re.search(r"^>\s*\*\*摘要\*\*:\s*(.+?)(?=\n\n|\n---|\Z)", body, re.DOTALL | re.MULTILINE)
    if not m:
        return "", body
    summary = m.group(1).strip().replace("\n", " ")
    body = body[: m.start()] + body[m.end():]
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    # Also remove leading '---' separator if it became orphan
    body = re.sub(r"^---\s*\n", "", body)
    return summary, body


# ---------- wall-of-text handling ----------

# A wall-of-text paragraph: single line that starts with `**` and ends with `**`,
# and contains the `****` separator inside.
WALL_LINE_RE = re.compile(r"^\*\*([^\n]+)\*\*$")


def split_wall_paragraph(line: str) -> str:
    """Convert a wall-of-text paragraph into structured markdown."""
    inner = line[2:-2]  # strip outer **
    # Split on `****` (the author's inline emphasis-within-emphasis marker).
    parts = re.split(r"\*{4,}", inner)

    out_lines: list[str] = []

    header_text = None
    first = parts[0].lstrip()
    # Pattern A: "一、xxx" / "二、xxx" Chinese roman numeral header
    m_roman = re.match(r"^([一二三四五六七八九十]+、[^\n]{2,200}?)(?:[。\n]|$)", first)
    # Pattern B: "市场聚焦的分支：DCI和OCS。..." — capture up to first 。
    m_branch = re.match(r"^(市场聚焦的分支[：:][^。]+)。\s*", first)
    # Pattern C: short "XX观点：" / "XX：" prefix
    m_short = re.match(r"^([^：。\n]{2,18}[：:])\s*", first)

    if m_roman:
        header_text = m_roman.group(1).rstrip("。 ")
        parts[0] = first[m_roman.end():].lstrip("。 ")
    elif m_branch:
        header_text = m_branch.group(1)
        parts[0] = first[m_branch.end():]
    elif m_short:
        header_text = m_short.group(1).rstrip("：:")
        parts[0] = first[m_short.end():]

    if header_text:
        out_lines.append(f"## {header_text}")
        out_lines.append("")

    # Render parts: even index → normal paragraph, odd index → key callout
    for i, seg in enumerate(parts):
        seg = seg.strip().lstrip("。；;:：，,")
        seg = seg.strip()
        if not seg:
            continue
        if i % 2 == 1:
            seg_clean = seg.rstrip("。；;").strip()
            out_lines.append(f"> 💡 **要点**: {seg_clean}。")
        else:
            out_lines.append(seg)
        out_lines.append("")

    return "\n".join(out_lines).strip()


def clean_walls(body: str) -> str:
    """Find wall-of-text paragraphs (entirely wrapped in **) and convert them."""
    out_paragraphs = []
    for para in re.split(r"\n\s*\n", body):
        para_stripped = para.strip()
        if (
            para_stripped.startswith("**")
            and para_stripped.endswith("**")
            and "\n" not in para_stripped
            and len(para_stripped) > 80
            # Must be a single bold span — i.e. no internal `**` toggling that
            # leaves a paragraph half-bold half-not. We look for an even count
            # of `**` (treating `****` as 2).
            and (para_stripped.count("**") % 2 == 0)
        ):
            out_paragraphs.append(split_wall_paragraph(para_stripped))
        else:
            out_paragraphs.append(para_stripped)
    return "\n\n".join(p for p in out_paragraphs if p)


# ---------- thesis-style 一、二、三 headers ----------

def promote_roman_headers(body: str) -> str:
    """Promote `**一、xxx**` patterns to `## 一、xxx`."""
    return re.sub(
        r"^\*\*([一二三四五六七八九十]+、[^\n]{2,200})\*\*$",
        r"## \1",
        body,
        flags=re.MULTILINE,
    )


# ---------- main per-file pipeline ----------

def clean_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(raw)
    body = strip_dup_metadata(body)
    summary, body = extract_summary(body)
    body = promote_roman_headers(body)
    body = clean_walls(body)

    parts = [build_meta_header(meta)]
    if summary:
        parts.append("---")
        parts.append(f"> 📌 **摘要**: {summary}")
    parts.append("---")
    parts.append(body)
    return "\n\n".join(parts).rstrip() + "\n"


# ---------- update via lark-cli ----------

def update_doc(doc_url: str, markdown: str) -> dict:
    cmd = [
        "lark-cli", "docs", "+update",
        "--doc", doc_url,
        "--mode", "overwrite",
        "--markdown", markdown,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        return {"ok": False, "error": f"exit={r.returncode} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"non-JSON: {r.stdout[:300]}"}


def main():
    log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    by_title = {entry["title"]: entry for entry in log if entry.get("ok")}

    out = []
    for subdir in ("01_thesis", "02_notes", "03_weekly"):
        files = sorted((ROOT / subdir).glob("*.md"))
        print(f"\n=== {subdir} ===")
        for f in files:
            title = f.stem
            entry = by_title.get(title)
            if not entry:
                print(f"  ⚠ no upload log entry for {title}, skip")
                continue

            cleaned = clean_file(f)
            print(f"  updating: {title}  ({len(cleaned)} chars)...", end=" ", flush=True)
            res = update_doc(entry["url"], cleaned)
            if res.get("ok"):
                print("✓")
                out.append({"title": title, "ok": True})
            else:
                err = res.get("error") or res.get("data") or res
                print(f"✗ {str(err)[:160]}")
                out.append({"title": title, "ok": False, "err": str(err)[:300]})

    ok = sum(1 for r in out if r["ok"])
    print(f"\n=== DONE: {ok}/{len(out)} updated ===")
    (ROOT / "_lark_cleanup_log.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
