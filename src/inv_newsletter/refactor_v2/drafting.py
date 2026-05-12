"""Stage B: Per-sector drafting.

For each sector that has triage content, compose a system prompt (contract +
writing_style + evidence_rules + sector_prompts/<sector>) and a user message
that contains:
  - the sector's triage entry (must respect importance ordering)
  - the email/meritco source bodies relevant to this sector
  - cross_source claims license
  - anchor-trap link warnings for this sector
  - already-written sections from prior sectors as coherence context

Stage B output is one .md per sector, plus a list to be concatenated by Stage C.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import anthropic

from .compose import load_contract, load_evidence_rules, load_sector_prompt, load_writing_style
from .cost import CostLedger

logger = logging.getLogger(__name__)


def _build_system_prompt(sector_name: str) -> str:
    """Compose the layered system prompt for a single sector draft call."""
    parts = [
        "You are a senior buyside equity analyst drafting one section of a daily investment research digest.",
        "Read the following three binding documents (output contract, writing style, evidence rules), then the sector-specific cues, then produce ONLY this sector's section in Chinese.",
        "",
        "=" * 70,
        "# Output Contract",
        "=" * 70,
        load_contract(),
        "",
        "=" * 70,
        "# Writing Style",
        "=" * 70,
        load_writing_style(),
        "",
        "=" * 70,
        "# Evidence Rules",
        "=" * 70,
        load_evidence_rules(),
        "",
        "=" * 70,
        f"# Sector Cues — {sector_name}",
        "=" * 70,
        load_sector_prompt(sector_name),
        "",
        "=" * 70,
        "# Output Requirements For This Call",
        "=" * 70,
        f"- Write ONLY the `## {sector_name}` section. Start with `## {sector_name}` as the heading.",
        "- Follow the theme order in the triage outline EXACTLY. Do not re-rank, add, or drop themes.",
        "- Single-source short items go in `### 简短跟踪` at the end of the section, NOT as `###` themes.",
        "- Use already-written sections (provided as context) to avoid duplicating discussion of the same Ticker.",
        "- Preserve every sell-side research URL from the source emails. Anchor-trap links (`[notes]`, `[here]`, `[link]`) are the highest-value ones — preserve them with descriptive labels.",
        "- Only write `两家共识 / 多家覆盖 / 卖方分歧` when the cross-source license confirms ≥2 sources for that ticker/theme.",
        "- Embed images using `IMG_NN` IDs only from the listed inventory; obey the three image rules.",
        "- Output the section markdown only, no commentary, no JSON, no code fences.",
    ]
    return "\n".join(parts)


def _select_relevant_sources(sector_entry: dict, source_map: dict[str, dict]) -> list[tuple[str, dict]]:
    """Return ordered (source_id, source_info) list for sources cited by this sector's themes + short tracking."""
    relevant_ids: list[str] = []
    seen: set[str] = set()
    for theme in sector_entry.get("themes", []):
        for sid in theme.get("sources", []):
            if sid not in seen and sid in source_map:
                relevant_ids.append(sid)
                seen.add(sid)
    for st in sector_entry.get("short_tracking", []):
        sid = st.get("source")
        if sid and sid not in seen and sid in source_map:
            relevant_ids.append(sid)
            seen.add(sid)
    return [(sid, source_map[sid]) for sid in relevant_ids]


def _build_user_blocks(
    *,
    sector_entry: dict,
    relevant_sources: list[tuple[str, dict]],
    cross_source: dict,
    link_inventory: dict,
    image_inventory: dict,  # {img_id: {path, media_type, caption, source_idx}}
    relevant_image_ids: list[str],
    already_written: str,
) -> list[dict]:
    """Build the multimodal user content blocks (text + images)."""
    sector_name = sector_entry["name"]
    blocks: list[dict] = []

    # 1. Triage outline for this sector (the structural spine — must be respected verbatim)
    triage_view = {
        "name": sector_entry["name"],
        "themes": sector_entry.get("themes", []),
        "short_tracking": sector_entry.get("short_tracking", []),
    }
    blocks.append({
        "type": "text",
        "text": (
            f"## TRIAGE OUTLINE FOR `{sector_name}` (binding — write themes in this exact order)\n\n"
            f"```json\n{json.dumps(triage_view, ensure_ascii=False, indent=2)}\n```\n"
        ),
    })

    # 2. Cross-source license (the only place "两家共识 / 卖方分歧" wording is permitted)
    cs_tickers = cross_source.get("cross_source_tickers", {})
    cs_themes = cross_source.get("cross_source_themes", {})
    cs_lines = [f"## CROSS-SOURCE LICENSE (only these may use 两家共识 / 卖方分歧 wording)"]
    if cs_themes:
        cs_lines.append("\n### 跨源主题（≥2 源）")
        for theme, sources in cs_themes.items():
            cs_lines.append(f"- **{theme}** ← {', '.join(sources)}")
    if cs_tickers:
        cs_lines.append("\n### 跨源 Ticker（≥2 源）")
        for tk, sources in sorted(cs_tickers.items()):
            cs_lines.append(f"- **{tk}** ← {', '.join(sources)}")
    if not cs_themes and not cs_tickers:
        cs_lines.append("\n_本日全部为单源覆盖，不能写跨源声明。_")
    blocks.append({"type": "text", "text": "\n".join(cs_lines)})

    # 3. Anchor-trap link warnings — extract entries from inventory whose email_idx
    #    belongs to this sector's relevant sources
    relevant_email_idxs = {info["idx"] for _, info in relevant_sources if info["kind"] == "email"}
    relevant_anchor_traps = [
        e for e in link_inventory.get("entries", [])
        if e["email_idx"] in relevant_email_idxs and e["anchor_trap"]
    ]
    if relevant_anchor_traps:
        at_lines = ["## ANCHOR-TRAP LINKS (preserve these sell-side report URLs with descriptive labels)"]
        for e in relevant_anchor_traps[:30]:
            target = e.get("unwrapped_url") or e["url"]
            at_lines.append(f"- `[{e['anchor_text']}]` → {e['subcategory']} — {target[:90]}")
        blocks.append({"type": "text", "text": "\n".join(at_lines)})

    # 4. Source bodies (only the ones relevant to this sector)
    blocks.append({
        "type": "text",
        "text": f"\n## RAW SOURCES FOR `{sector_name}` ({len(relevant_sources)} items)\n",
    })
    for sid, info in relevant_sources:
        if info["kind"] == "email":
            email = info["email"]
            fm = email["frontmatter"]
            blocks.append({
                "type": "text",
                "text": (
                    f"\n--- source_id: `{sid}` (email) ---\n"
                    f"subject: {fm.get('subject', '?')}\n"
                    f"sender: {fm.get('sender_name', '?')} <{fm.get('sender_address', '?')}>\n"
                    f"received: {fm.get('received_at', '?')}\n\n"
                    f"{email.get('body', '')}\n"
                ),
            })
        else:
            m = info["entry"]
            fm = m["frontmatter"]
            blocks.append({
                "type": "text",
                "text": (
                    f"\n--- source_id: `{sid}` (meritco) ---\n"
                    f"date: {m.get('date', '?')}\n"
                    f"industry: {fm.get('industry', '?')}\n"
                    f"tickers: {fm.get('tickers', [])}\n"
                    f"title: {fm.get('subject', '?')}\n"
                    f"source_url: {m.get('source_url', '?')}\n\n"
                    f"{m.get('body', '')}\n"
                ),
            })

    # 5. Image inventory + actual images for this sector
    if relevant_image_ids:
        inventory_lines = "\n".join(
            f"- `{img_id}`: {image_inventory[img_id]['caption']}"
            for img_id in relevant_image_ids
        )
        blocks.append({
            "type": "text",
            "text": (
                f"\n## IMAGE INVENTORY FOR `{sector_name}` ({len(relevant_image_ids)} images)\n"
                f"{inventory_lines}\n\n"
                "⛔ Three hard rules:\n"
                "1. NEVER reference an ID outside this inventory\n"
                "2. EACH ID at most one reference in your entire output\n"
                "3. Caption must visually match the image content\n"
            ),
        })
        for img_id in relevant_image_ids:
            entry = image_inventory[img_id]
            try:
                data = base64.standard_b64encode(Path(entry["path"]).read_bytes()).decode()
                blocks.append({"type": "text", "text": f"\n[{img_id}] {entry['caption']}\n"})
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": entry["media_type"], "data": data},
                })
            except Exception as e:
                logger.warning(f"Failed to attach image {img_id}: {e}")
    else:
        blocks.append({
            "type": "text",
            "text": f"\n## IMAGE INVENTORY FOR `{sector_name}`\n\n_No images available for this sector. Do not use any IMG_NN references._\n",
        })

    # 6. Already-written sections (for coherence + de-duplication)
    if already_written.strip():
        blocks.append({
            "type": "text",
            "text": (
                f"\n## SECTIONS ALREADY WRITTEN (for context only — DO NOT REWRITE)\n\n"
                f"{already_written}\n"
            ),
        })
    else:
        blocks.append({
            "type": "text",
            "text": "\n## SECTIONS ALREADY WRITTEN\n\n_(none — this is the first sector)_\n",
        })

    # 7. Final instruction
    blocks.append({
        "type": "text",
        "text": (
            f"\n## OUTPUT NOW\n\n"
            f"Write the `## {sector_name}` section markdown. Start with the H2 heading. "
            f"No prose wrapper, no commentary, no JSON. Output the section only.\n"
        ),
    })

    return blocks


def _relevant_image_ids(image_inventory: dict, relevant_email_idxs: set[int]) -> list[str]:
    return [
        img_id for img_id, entry in image_inventory.items()
        if entry["source_idx"] in relevant_email_idxs
    ]


def run_sector_drafting(
    *,
    client: anthropic.Anthropic,
    model: str,
    sectors: list[str],
    triage: dict,
    source_map: dict[str, dict],
    cross_source: dict,
    link_inventory: dict,
    image_inventory: dict,
    output_dir: Path,
    ledger: CostLedger,
    max_tokens_per_sector: int = 8000,
) -> list[str]:
    """Draft each sector in fixed order. Returns ordered list of sector markdown strings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    drafts: list[str] = []
    already_written = ""

    triage_by_name = {s["name"]: s for s in triage.get("sectors", [])}

    for i, sector_name in enumerate(sectors, 1):
        entry = triage_by_name.get(sector_name)
        if not entry:
            logger.info(f"[Stage B {i}/{len(sectors)}] `{sector_name}` — no triage content, skipping")
            continue
        themes = entry.get("themes", [])
        short = entry.get("short_tracking", [])
        if not themes and not short:
            logger.info(f"[Stage B {i}/{len(sectors)}] `{sector_name}` — empty, skipping")
            continue

        relevant_sources = _select_relevant_sources(entry, source_map)
        relevant_email_idxs = {info["idx"] for _, info in relevant_sources if info["kind"] == "email"}
        rel_img_ids = _relevant_image_ids(image_inventory, relevant_email_idxs)

        system_prompt = _build_system_prompt(sector_name)
        user_blocks = _build_user_blocks(
            sector_entry=entry,
            relevant_sources=relevant_sources,
            cross_source=cross_source,
            link_inventory=link_inventory,
            image_inventory=image_inventory,
            relevant_image_ids=rel_img_ids,
            already_written=already_written,
        )

        logger.info(
            f"[Stage B {i}/{len(sectors)}] `{sector_name}` — "
            f"{len(themes)} themes, {len(short)} short, "
            f"{len(relevant_sources)} sources, {len(rel_img_ids)} images"
        )

        t0 = time.perf_counter()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens_per_sector,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_blocks}],
        )
        duration = time.perf_counter() - t0
        stage_label = f"stage_b_{i:02d}_{sector_name.replace(' ', '_').replace('/', '_')}"
        ledger.record(
            stage=stage_label,
            model=model,
            usage=response.usage,
            duration_sec=duration,
            note=f"themes={len(themes)},sources={len(relevant_sources)},images={len(rel_img_ids)}",
        )

        section_md = response.content[0].text.strip()
        sector_file = output_dir / f"sector_{i:02d}_{sector_name}.md"
        sector_file.write_text(section_md, encoding="utf-8")
        drafts.append(section_md)
        already_written = (already_written + "\n\n" + section_md) if already_written else section_md
        logger.info(
            f"[Stage B {i}/{len(sectors)}] `{sector_name}` done in {duration:.1f}s, "
            f"{response.usage.input_tokens:,}→{response.usage.output_tokens:,} tok"
        )

    return drafts
