"""digest_v3 stage: deterministic chunking of regularized emails into chunks.json.

Reads upstream-regularized markdown (``output/daily/<date>/v3/formatted/<slug>.md``)
and the original email dirs (``data/mail/<date>/<slug>/``), then emits text chunks
(one per top-level ``- `` bullet / paragraph) plus image chunks (one per
chart-worthy image selected by :func:`images._select_key_images`).

No LLM calls — pure string + filesystem work. Captions are left empty here and
filled by a later stage.

CLI::

    uv run python -m inv_newsletter.digest_v3.chunk <date>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ..images import _select_key_images

# ── tuning constants ─────────────────────────────────────────────────────
MIN_CHUNK_CHARS = 120          # merge anything shorter into the previous chunk
LOW_STRUCTURE_MIN_CHARS = 1800  # "blob" detection: large …
LOW_STRUCTURE_MAX_NEWLINES = 3  # … AND very few line breaks


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body (mirrors summarizer._parse_frontmatter)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


def _split_sections(markdown: str) -> list[str]:
    """Split regularized markdown into ``## heading`` section bodies.

    Each returned string starts at a ``## `` line and runs until the next one.
    Any preamble before the first ``## `` is treated as its own leading block so
    no content is silently dropped.
    """
    lines = markdown.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not starts:
        return [markdown] if markdown.strip() else []

    sections: list[str] = []
    if starts[0] > 0:
        preamble = "\n".join(lines[: starts[0]]).strip()
        if preamble:
            sections.append(preamble)
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        sections.append("\n".join(lines[start:end]).strip())
    return sections


def _split_section_into_units(section: str) -> list[str]:
    """Split one section into raw chunk units (before short-merge).

    A unit is one top-level ``- `` bullet plus all its nested sub-bullets and
    continuation lines (everything until the next top-level ``- ``). A leading
    ``## heading`` line is attached to the first unit so the section title is not
    lost. If the section has no top-level bullets, split by blank-line paragraphs.
    """
    lines = section.split("\n")

    heading = ""
    body_start = 0
    if lines and lines[0].startswith("## "):
        heading = lines[0]
        body_start = 1
    body_lines = lines[body_start:]

    def _is_top_bullet(ln: str) -> bool:
        return ln.startswith("- ") or ln.strip() == "-"

    has_bullets = any(_is_top_bullet(ln) for ln in body_lines)

    units: list[str] = []
    if has_bullets:
        current: list[str] = []
        for ln in body_lines:
            if _is_top_bullet(ln) and current:
                units.append("\n".join(current).rstrip())
                current = [ln]
            else:
                current.append(ln)
        if current:
            units.append("\n".join(current).rstrip())
    else:
        # paragraph split on blank lines
        para: list[str] = []
        for ln in body_lines:
            if ln.strip() == "":
                if para:
                    units.append("\n".join(para).rstrip())
                    para = []
            else:
                para.append(ln)
        if para:
            units.append("\n".join(para).rstrip())

    # drop empties; attach heading to the first surviving unit
    units = [u for u in units if u.strip()]
    if heading:
        if units:
            units[0] = f"{heading}\n{units[0]}".rstrip()
        else:
            units = [heading]
    return units


def _merge_short(units: list[str]) -> list[str]:
    """Merge any unit shorter than MIN_CHUNK_CHARS into the previous chunk.

    If the very first unit is short it is merged forward into the next one so no
    content is dropped.
    """
    merged: list[str] = []
    for unit in units:
        if not merged:
            merged.append(unit)
            continue
        if len(unit) < MIN_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]}\n{unit}".rstrip()
        else:
            merged.append(unit)
    # handle a short leading chunk that never had a predecessor to merge into
    if len(merged) >= 2 and len(merged[0]) < MIN_CHUNK_CHARS:
        merged[1] = f"{merged[0]}\n{merged[1]}".rstrip()
        merged = merged[1:]
    return merged


def _is_low_structure(text: str) -> bool:
    """A 'blob': unusually large with very few newlines."""
    return (
        len(text) > LOW_STRUCTURE_MIN_CHARS
        and text.count("\n") < LOW_STRUCTURE_MAX_NEWLINES
    )


def _chunk_email(slug: str, markdown: str) -> list[dict]:
    """Build text chunks for one regularized email."""
    units: list[str] = []
    for section in _split_sections(markdown):
        units.extend(_split_section_into_units(section))
    units = _merge_short(units)

    chunks: list[dict] = []
    for i, text in enumerate(units, start=1):
        chunks.append({
            "chunk_id": f"{slug}_CHK_{i:02d}",
            "source_slug": slug,
            "type": "text",
            "text": text,
            "low_structure": _is_low_structure(text),
        })
    return chunks


def build_chunks(date: str, repo_root: Path | None = None) -> dict:
    """Build the full chunks.json payload for ``date``.

    Returns the dict written to disk (does not write it). Raises FileNotFoundError
    with a clear message if the formatted dir is missing.
    """
    root = repo_root or Path.cwd()
    formatted_dir = root / "output" / "daily" / date / "v3" / "formatted"
    mail_dir = root / "data" / "mail" / date

    if not formatted_dir.is_dir():
        raise FileNotFoundError(
            f"Formatted dir not found: {formatted_dir}\n"
            f"Expected upstream-regularized files at output/daily/{date}/v3/formatted/<slug>.md"
        )

    formatted_files = sorted(formatted_dir.glob("*.md"))
    if not formatted_files:
        raise FileNotFoundError(f"No *.md files in {formatted_dir}")

    all_chunks: list[dict] = []
    summary_rows: list[tuple[str, int, int]] = []
    global_img_n = 0

    for fpath in formatted_files:
        slug = fpath.stem
        markdown = fpath.read_text(encoding="utf-8")

        # text chunks
        text_chunks = _chunk_email(slug, markdown)
        all_chunks.extend(text_chunks)

        # image chunks — read original email frontmatter for the images: list
        email_dir = mail_dir / slug
        img_count = 0
        if email_dir.is_dir():
            email_md = email_dir / "email.md"
            image_names: list[str] = []
            if email_md.exists():
                fm, _ = _parse_frontmatter(email_md.read_text(encoding="utf-8"))
                image_names = fm.get("images", []) or []
            selected = _select_key_images(email_dir, image_names)
            for img in selected:
                global_img_n += 1
                all_chunks.append({
                    "chunk_id": f"IMG_{global_img_n:02d}",
                    "source_slug": slug,
                    "type": "image",
                    "image_path": str(img["path"].resolve()),
                    "caption": "",
                })
            img_count = len(selected)

        summary_rows.append((slug, len(text_chunks), img_count))

    payload = {"date": date, "chunks": all_chunks}

    # ── print summary ────────────────────────────────────────────────
    total_text = sum(r[1] for r in summary_rows)
    print(f"chunks for {date}:")
    for slug, n_text, n_img in summary_rows:
        print(f"  {slug}: {n_text} text, {n_img} image")
    print(f"  TOTAL: {total_text} text chunks, {global_img_n} image chunks "
          f"({len(all_chunks)} chunks)")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inv_newsletter.digest_v3.chunk",
        description="Deterministically chunk regularized emails into chunks.json.",
    )
    parser.add_argument("date", help="Target date, e.g. 2026-06-08")
    args = parser.parse_args(argv)

    try:
        payload = build_chunks(args.date)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out_path = Path.cwd() / "output" / "daily" / args.date / "v3" / "chunks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {out_path}")

    # ── per-email slices: one file per source_slug with only its chunks ──
    by_email: dict[str, list[dict]] = {}
    for chunk in payload["chunks"]:
        by_email.setdefault(chunk["source_slug"], []).append(chunk)

    slices_dir = out_path.parent / "chunks_by_email"
    slices_dir.mkdir(parents=True, exist_ok=True)
    for slug, slug_chunks in by_email.items():
        slice_payload = {
            "date": args.date,
            "source_slug": slug,
            "chunks": slug_chunks,
        }
        (slices_dir / f"{slug}.json").write_text(
            json.dumps(slice_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"wrote {len(by_email)} per-email slices to chunks_by_email/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
