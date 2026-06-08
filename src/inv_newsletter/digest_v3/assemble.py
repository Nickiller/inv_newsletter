"""digest_v3 stage: deterministic assembly + finalize.

``assemble``  concatenates CC-written section drafts, enforces canonical sector
              order, appends the optional catalyst (本周关注) block, validates and
              embeds IMG_NN image references, and writes ``v3/body.md``.
``finalize``  prepends the ``## 今日要点`` TL;DR block to the body and writes the
              published file ``output/daily/<date>_daily_digest_v3.md``.

No LLM calls — pure string + filesystem work, reusing helpers from images.py,
postprocess.py and tldr.py.

CLI::

    uv run python -m inv_newsletter.digest_v3.assemble assemble <date>
    uv run python -m inv_newsletter.digest_v3.assemble finalize <date>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..images import _embed_images, _validate_image_refs
from ..postprocess import _reorder_sections
from ..tldr import prepend_tldr

# sector-name → ascii-slug (must match prompts/sections/<slug>.md filenames).
# Iteration order here = the order drafts are concatenated *before* reordering;
# _reorder_sections then enforces the canonical taxonomy order regardless.
SECTOR_SLUGS: dict[str, str] = {
    "AI 模型与平台": "ai_platform",
    "宏观与市场": "macro",
    "半导体与硬件": "semi_hardware",
    "互联网与数字广告": "internet",
    "软件与SaaS": "software_saas",
    "其他": "other",
}


def _v3_dir(date: str, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    return root / "output" / "daily" / date / "v3"


def _build_image_maps(chunks_path: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """Read chunks.json → (IMG_NN → Path map, IMG_NN → caption map).

    Returns empty maps if chunks.json is missing.
    """
    img_map: dict[str, Path] = {}
    img_caption: dict[str, str] = {}
    if not chunks_path.exists():
        return img_map, img_caption
    data = json.loads(chunks_path.read_text(encoding="utf-8"))
    for chunk in data.get("chunks", []):
        if chunk.get("type") != "image":
            continue
        img_id = chunk["chunk_id"]
        img_map[img_id] = Path(chunk["image_path"])
        img_caption[img_id] = chunk.get("caption", "") or ""
    return img_map, img_caption


def assemble(date: str, repo_root: Path | None = None) -> Path:
    """Assemble section drafts → v3/body.md. Returns the written path."""
    root = repo_root or Path.cwd()
    v3 = _v3_dir(date, root)
    sections_dir = v3 / "sections"

    # 1. Concatenate existing section drafts (in mapping order; reorder fixes it).
    included: list[str] = []
    parts: list[str] = []
    for sector_name, slug in SECTOR_SLUGS.items():
        draft = sections_dir / f"{slug}.md"
        if not draft.exists():
            continue
        text = draft.read_text(encoding="utf-8").strip()
        if not text:
            continue
        parts.append(text)
        included.append(sector_name)

    if not parts:
        raise FileNotFoundError(
            f"No section drafts found in {sections_dir} (expected <slug>.md files)"
        )

    combined = "\n\n".join(parts)

    # 1b. Enforce canonical sector + industry order.
    combined = _reorder_sections(combined)

    # 2. Append catalyst (本周关注) block if present.
    catalyst_path = v3 / "catalyst.md"
    has_catalyst = catalyst_path.exists() and catalyst_path.read_text(encoding="utf-8").strip()
    if has_catalyst:
        combined = combined.rstrip() + "\n\n" + catalyst_path.read_text(encoding="utf-8").strip() + "\n"

    # 3. Prepend H1 title if not already present.
    title = f"# Daily Research Digest — {date}"
    if not combined.lstrip().startswith("# "):
        combined = f"{title}\n\n{combined.lstrip()}"

    # 4. Validate + embed image refs.
    chunks_path = v3 / "chunks.json"
    img_map, img_caption = _build_image_maps(chunks_path)
    combined = _validate_image_refs(combined, img_caption)
    img_dir = root / "output" / "daily" / date
    combined = _embed_images(combined, img_map, img_dir, date)

    # 5. Write body.md
    body_path = v3 / "body.md"
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(combined.rstrip() + "\n", encoding="utf-8")

    # ── report ───────────────────────────────────────────────────────
    print(f"assembled body for {date}:")
    print(f"  sectors included: {', '.join(included) if included else '(none)'}")
    print(f"  catalyst (本周关注): {'yes' if has_catalyst else 'no'}")
    remaining = sorted(i for i in img_map if i in combined)
    print(f"  images embedded: {len(remaining)} / {len(img_map)} cataloged"
          + (f" (dropped: {', '.join(i for i in sorted(img_map) if i not in remaining)})"
             if len(remaining) < len(img_map) else ""))
    print(f"  wrote {body_path}")
    return body_path


def finalize(date: str, repo_root: Path | None = None) -> Path:
    """Prepend TL;DR to body.md → published <date>_daily_digest_v3.md."""
    root = repo_root or Path.cwd()
    v3 = _v3_dir(date, root)

    body_path = v3 / "body.md"
    if not body_path.exists():
        raise FileNotFoundError(f"body.md not found: {body_path} (run `assemble` first)")
    tldr_path = v3 / "tldr.md"
    if not tldr_path.exists():
        raise FileNotFoundError(f"tldr.md not found: {tldr_path}")

    body = body_path.read_text(encoding="utf-8")
    tldr = tldr_path.read_text(encoding="utf-8")
    final = prepend_tldr(body, tldr)

    final_path = root / "output" / "daily" / f"{date}_daily_digest_v3.md"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(final.rstrip() + "\n", encoding="utf-8")
    print(f"finalized {date}: wrote {final_path}")
    return final_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inv_newsletter.digest_v3.assemble",
        description="Assemble v3 section drafts into the final digest body / finalize with TL;DR.",
    )
    parser.add_argument("subcommand", choices=["assemble", "finalize"])
    parser.add_argument("date", help="Target date, e.g. 2026-06-08")
    args = parser.parse_args(argv)

    try:
        if args.subcommand == "assemble":
            assemble(args.date)
        else:
            finalize(args.date)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
