"""Orchestrator: runs Stage A → packets → Stage B → Stage C → validators.

Reuses _load_emails / _load_meritco / _caption_all_images / _validate_image_refs /
_embed_images / _select_key_images / _media_type from the existing summarizer.py
to keep image discipline identical between v1 and v2.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import yaml

from ..summarizer import (
    _caption_all_images,
    _embed_images,
    _load_emails,
    _load_meritco,
    _media_type,
    _select_key_images,
    _validate_image_refs,
)
from .compose import load_sectors
from .cost import CostLedger
from .drafting import run_sector_drafting
from .finalize import assemble_digest, run_catalyst_calendar
from .packets import (
    build_cross_source_from_triage,
    build_delta_packet,
    build_link_inventory,
    write_cross_source_helper,
    write_delta_helper,
    write_link_helper,
)
from .triage import run_triage, write_triage_helper
from .validators import write_audit_report

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "claude-opus-4-7"


def run_pipeline(
    *,
    target_date: str,
    data_mail_dir: Path,
    meritco_dir: Path | None,
    meritco_days: int = 3,
    output_dir: Path,
    filters_yaml: Path,
    model: str = DEFAULT_MODEL,
    triage_model: str | None = None,
    catalyst_model: str | None = None,
    max_tokens_per_sector: int = 8000,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """End-to-end run. Returns summary dict with paths and totals."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    triage_model = triage_model or model
    catalyst_model = catalyst_model or model

    pipeline_t0 = time.perf_counter()

    # ----- Paths
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = output_dir / target_date / "refactor_v2"
    packets_dir = artifacts_dir / "packets"
    helpers_dir = artifacts_dir / "helpers"
    sectors_dir = artifacts_dir / "sectors"
    packets_dir.mkdir(parents=True, exist_ok=True)
    helpers_dir.mkdir(parents=True, exist_ok=True)
    sectors_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = artifacts_dir / "cost_ledger.json"
    ledger = CostLedger(ledger_path)

    # ----- Load sources
    date_dir = data_mail_dir / target_date
    emails = _load_emails(date_dir)
    logger.info(f"Loaded {len(emails)} emails from {date_dir}")

    meritco_entries: list[dict] = []
    if meritco_dir is not None and meritco_days > 0:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
        for offset in range(meritco_days):
            d = target_dt - timedelta(days=offset)
            day_dir = meritco_dir / d.isoformat()
            if day_dir.exists():
                meritco_entries.extend(_load_meritco(day_dir, d.isoformat()))
        logger.info(f"Loaded {len(meritco_entries)} meritco entries from past {meritco_days} day(s)")

    if not emails and not meritco_entries:
        raise RuntimeError(f"No emails or meritco entries for {target_date}")

    # ----- Sectors (single source of truth from filters.yaml)
    sectors = load_sectors(filters_yaml)
    logger.info(f"Sectors (from {filters_yaml.name}): {sectors}")

    # ----- Image captioning + inventory (reuse existing flow)
    pre_cap_t0 = time.perf_counter()
    captions = _caption_all_images(client, emails)
    logger.info(f"Image captioning took {time.perf_counter() - pre_cap_t0:.1f}s")

    # Build IMG_NN inventory: {img_id: {path, media_type, caption, source_idx}}
    image_inventory: dict[str, dict] = {}
    img_map: dict[str, Path] = {}  # for _embed_images later
    img_counter = 0
    for idx, email in enumerate(emails):
        for img in email["images"]:
            img_counter += 1
            img_id = f"IMG_{img_counter:02d}"
            caption = (captions.get(str(img["path"])) or "").strip()
            label = caption if caption else f"来自《{email['frontmatter'].get('subject', '')}》"
            image_inventory[img_id] = {
                "path": img["path"],
                "media_type": img["media_type"],
                "caption": label,
                "source_idx": idx,
            }
            img_map[img_id] = img["path"]

    # ----- Build packets (those that don't depend on triage)
    link_inventory = build_link_inventory(emails, packets_dir / "link_inventory.json")
    write_link_helper(link_inventory, helpers_dir / "link_helper.md")

    prior_day = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prior_day_digest_path = output_dir / f"{prior_day}_daily_digest.md"
    delta = build_delta_packet(prior_day_digest_path, packets_dir / "delta.json")
    write_delta_helper(delta, helpers_dir / "delta_helper.md")

    # ----- Stage A: Triage
    logger.info("=" * 60)
    logger.info("Stage A: Triage")
    logger.info("=" * 60)
    triage, source_map = run_triage(
        client=client,
        model=triage_model,
        sectors=sectors,
        emails=emails,
        meritco_entries=meritco_entries,
        delta=delta,
        output_path=packets_dir / "triage.json",
        ledger=ledger,
    )
    write_triage_helper(triage, helpers_dir / "triage_helper.md")

    cross_source = build_cross_source_from_triage(triage, packets_dir / "cross_source.json")
    write_cross_source_helper(cross_source, helpers_dir / "cross_source_helper.md")

    # ----- Stage B: per-sector drafting
    logger.info("=" * 60)
    logger.info("Stage B: Per-sector drafting")
    logger.info("=" * 60)
    sector_drafts = run_sector_drafting(
        client=client,
        model=model,
        sectors=sectors,
        triage=triage,
        source_map=source_map,
        cross_source=cross_source,
        link_inventory=link_inventory,
        image_inventory=image_inventory,
        output_dir=sectors_dir,
        ledger=ledger,
        max_tokens_per_sector=max_tokens_per_sector,
    )

    # ----- Stage C: catalyst calendar
    logger.info("=" * 60)
    logger.info("Stage C: Catalyst calendar")
    logger.info("=" * 60)
    source_concat_for_catalyst = "\n\n".join(
        f"## {sid}\n\n{(info['email']['body'] if info['kind'] == 'email' else info['entry']['body'])[:6000]}"
        for sid, info in source_map.items()
    )
    catalyst_section = run_catalyst_calendar(
        client=client,
        model=catalyst_model,
        sector_drafts=sector_drafts,
        source_bodies_concat=source_concat_for_catalyst,
        ledger=ledger,
    )

    # ----- Assemble + image validation + embed
    digest_md = assemble_digest(
        target_date=target_date,
        sector_drafts=sector_drafts,
        catalyst_section=catalyst_section,
    )
    img_caption = {img_id: e["caption"] for img_id, e in image_inventory.items()}
    digest_md = _validate_image_refs(digest_md, img_caption)
    # Embed images: copy referenced ones into output_dir/{date}/
    img_out_dir = output_dir / target_date
    digest_md = _embed_images(digest_md, img_map, img_out_dir, target_date)

    # ----- Write final digest
    digest_path = output_dir / f"{target_date}_daily_digest_refactor_v2.md"
    digest_path.write_text(digest_md, encoding="utf-8")
    logger.info(f"Final digest written to {digest_path} ({len(digest_md):,} chars)")

    # ----- Audit validators (§6)
    audit_path = artifacts_dir / "audit_report.md"
    audit = write_audit_report(
        digest_text=digest_md,
        link_inventory=link_inventory,
        cross_source=cross_source,
        audit_path=audit_path,
    )

    # ----- Done
    total_duration = time.perf_counter() - pipeline_t0
    ledger.print_summary()
    logger.info(f"Pipeline complete in {total_duration:.1f}s")

    return {
        "digest_path": str(digest_path),
        "artifacts_dir": str(artifacts_dir),
        "audit_path": str(audit_path),
        "cost_ledger": ledger.totals(),
        "duration_sec": round(total_duration, 1),
        "stats": {
            "emails": len(emails),
            "meritco_entries": len(meritco_entries),
            "sectors_emitted": len(sector_drafts),
            "sell_side_link_coverage_pct": audit["link_coverage"]["sell_side_coverage_pct"],
            "anchor_trap_coverage_pct": audit["link_coverage"]["anchor_trap_coverage_pct"],
            "suspicious_cross_source_claims": audit["cross_source_claims"]["suspicious_count"],
        },
    }
