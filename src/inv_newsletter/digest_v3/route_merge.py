"""digest_v3 stage: deterministic merge of per-email routing outputs into route_map.json.

Reads the chunk inventory (``output/daily/<date>/v3/chunks.json``) and every
per-email route file (``output/daily/<date>/v3/routes/<slug>.json``), then:

1. Writes image captions discovered in the route files back into chunks.json.
2. Flattens routes into per-item records (text / excerpt / image).
3. Computes ``multi_source`` *by code* — a ticker is multi-source iff it appears
   across >=2 distinct ``source_slug`` values among non-DROP text items.
4. Buckets items into the 6 content sectors (primary / secondary / images),
   aggregates catalysts (conservative near-duplicate merge), collects dropped
   items, and emits stats.

No LLM calls — pure JSON + filesystem work. Sector order comes from the
taxonomy (``get_default_taxonomy().sector_order()``), excluding the meta
section 本周关注.

CLI::

    .venv/bin/python -m inv_newsletter.digest_v3.route_merge <date>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ..taxonomy import get_default_taxonomy

# Meta section that is not a content destination here.
_META_SECTION = "本周关注"
_DROP = "DROP"

# Sector name → slug (must match assemble.SECTOR_SLUGS and prompts/sections/*.md).
SECTOR_SLUGS: dict[str, str] = {
    "AI 模型与平台": "ai_platform",
    "宏观与市场": "macro",
    "半导体与硬件": "semi_hardware",
    "互联网与数字广告": "internet",
    "软件与SaaS": "software_saas",
    "其他": "other",
}

# Tickers that anchor a section even without a daily move (mega-cap + AI key
# mid-caps). Matched against _norm_ticker() output (upper-cased, $-stripped);
# includes name variants because routers emit both symbols (AVGO) and names
# (SK Hynix / Samsung).
ANCHOR_TICKERS: set[str] = {
    "NVDA", "AMZN", "GOOGL", "GOOG", "META", "AAPL", "MSFT", "TSLA", "BABA",
    "AMD", "AVGO", "MU", "TSM", "TSMC", "ASML",
    "SK HYNIX", "000660.KS", "SAMSUNG", "005930.KS",
    "DDOG", "NOW", "ORCL", "CRM", "PANW", "CRWD", "SNOW", "ADBE",
}


def _primary_sort_key(item: dict) -> tuple[int]:
    """Importance rank for ordering a sector's primary items (higher = earlier).

    Mirrors the legacy priority: anchor names first (PM daily-read anchors, even
    without a daily move), then multi-source *themes* (a topic ≥2 sellsiders
    converge on — the single most important signal), then headline-flagged
    events, then ticker-level multi-source.
    Python's sort is stable, so ties keep their original (slug+chunk) order.

    The anchor bonus keys on the **subject** ticker only (``tickers[0]``), not any
    mentioned ticker — otherwise a peer name-drop (e.g. a SAP preview that cites
    ORCL/CRM) wrongly inherits an anchor's weight and floats above real movers.
    """
    tickers = item.get("tickers") or []
    subject_is_anchor = bool(tickers) and _norm_ticker(tickers[0]) in ANCHOR_TICKERS
    score = (
        (1000 if subject_is_anchor else 0)
        + (300 if item.get("theme_multi_source") else 0)
        + (100 if item.get("headline") else 0)
        + (10 if item.get("multi_source") else 0)
    )
    return (-score,)


def _v3_dir(date: str, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    return root / "output" / "daily" / date / "v3"


def _content_sectors() -> list[str]:
    """Canonical content sectors in taxonomy order, minus the meta section."""
    return [s for s in get_default_taxonomy().sector_order() if s != _META_SECTION]


def _norm_event(event: str) -> str:
    """Normalize a catalyst event string for conservative dedup comparison."""
    if not event:
        return ""
    return re.sub(r"[\s\W_]+", "", event, flags=re.UNICODE).lower()


def _norm_ticker(t: str) -> str:
    if not t:
        return ""
    return t.strip().lstrip("$").upper()


def _clean_theme(theme: str | None) -> str | None:
    """Return a stripped theme tag, or None for empty/null-ish values."""
    if theme is None:
        return None
    s = theme.strip()
    if not s or s.lower() in {"null", "none", "n/a"}:
        return None
    return s


def _norm_theme(theme: str | None) -> str:
    """Normalize a theme tag for cross-email grouping.

    Strips whitespace/punctuation and lowercases so per-email routers that emit
    e.g. ``800VDC`` / ``800V DC`` collapse to the same key. CJK chars are kept
    (they count as word chars under re.UNICODE). Synonyms that don't normalize
    to the same string (``800VDC`` vs ``±400V``) are out of scope for this code
    pass — escalate to an LLM theme-merge stage if exact-after-normalize misses.
    """
    if not theme:
        return ""
    return re.sub(r"[\s\W_]+", "", theme, flags=re.UNICODE).lower()


def _load_routes(routes_dir: Path) -> dict[str, list[dict]]:
    """Load all routes/<slug>.json files → {slug: [route_obj, ...]}."""
    out: dict[str, list[dict]] = {}
    for fpath in sorted(routes_dir.glob("*.json")):
        slug = fpath.stem
        data = json.loads(fpath.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{fpath}: expected a JSON array, got {type(data).__name__}")
        out[slug] = data
    return out


def _load_image_routes(v3_dir: Path) -> dict[str, dict]:
    """Load image-route overrides from v3/image_routes/*.json (per-email arrays).

    Each file is a JSON array of ``{img_id, caption, primary, tickers}`` produced
    by the vision image-route stage (CC subagents). Returns
    ``{img_id: {"primary", "caption", "tickers"}}``. Missing dir → empty dict.

    Images are routed *here* (by vision), decoupled from the text router — the
    text-only router cannot see images and would DROP them all.
    """
    out: dict[str, dict] = {}
    img_dir = v3_dir / "image_routes"
    if not img_dir.is_dir():
        return out
    for fpath in sorted(img_dir.glob("*.json")):
        data = json.loads(fpath.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for obj in data:
            iid = obj.get("img_id")
            if not iid:
                continue
            out[iid] = {
                "primary": obj.get("primary"),
                "caption": obj.get("caption") or "",
                "tickers": obj.get("tickers") or [],
            }
    return out


def _is_drop(sector: str | None) -> bool:
    return (sector or "").strip().upper() == _DROP


def _clean_sector(sector: str | None) -> str | None:
    """Return a stripped sector name, or None for empty/null."""
    if sector is None:
        return None
    s = sector.strip()
    return s or None


def build_route_map(date: str, repo_root: Path | None = None) -> dict:
    """Build the route_map.json payload for ``date`` (also re-saves chunks.json).

    Raises FileNotFoundError with a clear message if chunks.json or the routes
    dir is missing.
    """
    v3 = _v3_dir(date, repo_root)
    chunks_path = v3 / "chunks.json"
    routes_dir = v3 / "routes"

    if not chunks_path.exists():
        raise FileNotFoundError(
            f"chunks.json not found: {chunks_path}\n"
            f"Run the chunk stage first (inv_newsletter.digest_v3.chunk {date})."
        )
    if not routes_dir.is_dir():
        raise FileNotFoundError(
            f"Routes dir not found: {routes_dir}\n"
            f"Expected per-email route files at output/daily/{date}/v3/routes/<slug>.json"
        )

    # ── 1. index chunks ──────────────────────────────────────────────────
    chunks_doc = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunk_by_id: dict[str, dict] = {c["chunk_id"]: c for c in chunks_doc.get("chunks", [])}

    content_sectors = _content_sectors()
    sector_set = set(content_sectors)

    # ── 2. load text routes + image-route overrides ─────────────────────
    routes_by_slug = _load_routes(routes_dir)
    image_routes = _load_image_routes(v3)  # {img_id: {primary, caption, tickers}}

    # write image captions (from the vision image-route stage) into chunks.json
    captions_written = 0
    for cid, ovr in image_routes.items():
        chunk = chunk_by_id.get(cid)
        if chunk is None or chunk.get("type") != "image":
            continue
        caption = ovr.get("caption")
        if caption and chunk.get("caption") != caption:
            chunk["caption"] = caption
            captions_written += 1
    if captions_written:
        chunks_path.write_text(
            json.dumps(chunks_doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── 3. flatten routes into items (ordered by slug then chunk order) ──
    items: list[dict] = []
    for slug in sorted(routes_by_slug):
        for robj in routes_by_slug[slug]:
            cid = robj.get("chunk_id")
            chunk = chunk_by_id.get(cid)
            ctype = chunk.get("type") if chunk else "text"
            low_structure = bool(chunk.get("low_structure")) if chunk else False
            chunk_text = chunk.get("text", "") if chunk else ""

            routes = robj.get("routes") or []

            if ctype == "image":
                # Images are routed by the dedicated vision image-route stage
                # (pass 3b below), NOT by the text router — skip here.
                continue

            # text chunk — normal: one route w/ chunk text; low_structure: each
            # route → item with text = route.excerpt.
            for route in routes:
                if low_structure:
                    text = route.get("excerpt") or ""
                else:
                    text = chunk_text
                items.append({
                    "chunk_id": cid,
                    "source_slug": slug,
                    "type": "text",
                    "primary": _clean_sector(route.get("primary")),
                    "secondary": _clean_sector(route.get("secondary")),
                    "tickers": list(route.get("tickers") or []),
                    "headline": bool(route.get("headline")),
                    "theme": _clean_theme(route.get("theme")),
                    "text": text,
                })

    # ── 3b. image items from chunks.json + vision image-route overrides ──
    # Decoupled from the text router: every image chunk is sourced here and
    # routed by its override (primary sector or DROP). No override → not routed.
    for chunk in chunks_doc.get("chunks", []):
        if chunk.get("type") != "image":
            continue
        cid = chunk["chunk_id"]
        ovr = image_routes.get(cid) or {}
        items.append({
            "chunk_id": cid,
            "source_slug": chunk.get("source_slug", ""),
            "type": "image",
            "primary": _clean_sector(ovr.get("primary")),
            "secondary": None,
            "tickers": list(ovr.get("tickers") or []),
            "caption": ovr.get("caption") or chunk.get("caption", "") or "",
        })

    # ── 4. multi_source (code) over non-DROP text items ──────────────────
    ticker_sources: dict[str, set[str]] = {}
    for it in items:
        if it["type"] != "text":
            continue
        if _is_drop(it["primary"]):
            continue
        for t in it["tickers"]:
            nt = _norm_ticker(t)
            if nt:
                ticker_sources.setdefault(nt, set()).add(it["source_slug"])

    multi_tickers = {t for t, srcs in ticker_sources.items() if len(srcs) >= 2}

    for it in items:
        it["multi_source"] = any(
            _norm_ticker(t) in multi_tickers for t in it["tickers"]
        )

    # ── 4b. theme multi_source (code) — a theme covered by >=2 distinct sources ──
    # The single most important signal: themes (not tickers) that multiple sellsiders
    # converge on. Per-email routers can't see "multi", so it can only be computed
    # here, globally, by grouping on the theme tag each chunk carries.
    theme_sources: dict[str, set[str]] = {}
    for it in items:
        if it["type"] != "text" or _is_drop(it["primary"]):
            continue
        nt = _norm_theme(it.get("theme"))
        if nt:
            theme_sources.setdefault(nt, set()).add(it["source_slug"])

    multi_themes = {t for t, srcs in theme_sources.items() if len(srcs) >= 2}

    for it in items:
        nt = _norm_theme(it.get("theme"))
        it["theme_multi_source"] = bool(nt) and nt in multi_themes

    # ── 5a. bucket into sectors ──────────────────────────────────────────
    sectors_out: dict[str, dict] = {
        s: {"primary": [], "secondary": [], "images": []} for s in content_sectors
    }
    dropped: list[dict] = []
    by_sector_primary: dict[str, int] = {s: 0 for s in content_sectors}
    images_routed = 0

    for it in items:
        if it["type"] == "image":
            primary = it["primary"]
            if primary in sector_set:
                sectors_out[primary]["images"].append({
                    "img_id": it["chunk_id"],
                    "source_slug": it["source_slug"],
                    "caption": it["caption"],
                })
                images_routed += 1
            continue

        # text item
        primary = it["primary"]
        if _is_drop(primary):
            dropped.append({
                "chunk_id": it["chunk_id"],
                "source_slug": it["source_slug"],
            })
            continue

        if primary in sector_set:
            sectors_out[primary]["primary"].append({
                "chunk_id": it["chunk_id"],
                "source_slug": it["source_slug"],
                "tickers": it["tickers"],
                "multi_source": it["multi_source"],
                "headline": it.get("headline", False),
                "theme": it.get("theme"),
                "theme_multi_source": it.get("theme_multi_source", False),
                "text": it["text"],
            })
            by_sector_primary[primary] += 1

        secondary = it["secondary"]
        if secondary in sector_set and not _is_drop(secondary):
            sectors_out[secondary]["secondary"].append({
                "chunk_id": it["chunk_id"],
                "source_slug": it["source_slug"],
                "tickers": it["tickers"],
                "text": it["text"],
            })

    # drop empty sectors (no primary/secondary/images content)
    sectors_final = {
        s: bucket
        for s, bucket in sectors_out.items()
        if bucket["primary"] or bucket["secondary"] or bucket["images"]
    }

    # ── 5b. aggregate catalysts (conservative near-duplicate merge) ──────
    catalysts = _merge_catalysts(routes_by_slug, chunk_by_id)

    multi_source_items = sum(
        1 for it in items if it["type"] == "text" and not _is_drop(it["primary"]) and it["multi_source"]
    )
    theme_multi_source_items = sum(
        1 for it in items if it["type"] == "text" and not _is_drop(it["primary"]) and it.get("theme_multi_source")
    )

    # representative original label + source count for each multi-source theme (display only)
    theme_label_by_norm: dict[str, str] = {}
    for it in items:
        nt = _norm_theme(it.get("theme"))
        if nt and nt not in theme_label_by_norm:
            theme_label_by_norm[nt] = _clean_theme(it.get("theme")) or nt
    multi_theme_summary = {
        theme_label_by_norm.get(t, t): len(theme_sources[t]) for t in sorted(multi_themes)
    }

    stats = {
        "total_items": len(items),
        "by_sector_primary": by_sector_primary,
        "dropped": len(dropped),
        "images_routed": images_routed,
        "multi_source_items": multi_source_items,
        "multi_source_themes": multi_theme_summary,
        "theme_multi_source_items": theme_multi_source_items,
        "catalysts": len(catalysts),
    }

    return {
        "date": chunks_doc.get("date", date),
        "sectors": sectors_final,
        "catalysts": catalysts,
        "dropped": dropped,
        "stats": stats,
    }


def _merge_catalysts(
    routes_by_slug: dict[str, list[dict]], chunk_by_id: dict[str, dict]
) -> list[dict]:
    """Aggregate catalysts across all route files, merging near-duplicates.

    Merge rule (conservative): two catalysts merge if (normalized event strings
    match) OR (same non-empty date AND overlapping tickers). Sources are unioned.
    When unsure, keep separate. Order preserved by first appearance (slug order,
    then chunk order).
    """
    merged: list[dict] = []

    def _same(a: dict, b_event_n: str, b_date: str, b_tickers: set[str]) -> bool:
        a_event_n = _norm_event(a["event"])
        if a_event_n and b_event_n and a_event_n == b_event_n:
            return True
        if a["date"] and b_date and a["date"] == b_date:
            if a["_tickers_n"] & b_tickers:
                return True
        return False

    for slug in sorted(routes_by_slug):
        for robj in routes_by_slug[slug]:
            for cat in robj.get("catalysts") or []:
                event = (cat.get("event") or "").strip()
                cdate = (cat.get("date") or "").strip()
                tickers = [t for t in (cat.get("tickers") or []) if t]
                tickers_n = {_norm_ticker(t) for t in tickers if _norm_ticker(t)}
                event_n = _norm_event(event)

                hit = None
                for existing in merged:
                    if _same(existing, event_n, cdate, tickers_n):
                        hit = existing
                        break

                if hit is not None:
                    if slug not in hit["sources"]:
                        hit["sources"].append(slug)
                    for t in tickers:
                        if t not in hit["tickers"]:
                            hit["tickers"].append(t)
                    hit["_tickers_n"] |= tickers_n
                    # keep first non-empty date / event
                    if not hit["date"] and cdate:
                        hit["date"] = cdate
                    if not hit["event"] and event:
                        hit["event"] = event
                else:
                    merged.append({
                        "date": cdate,
                        "event": event,
                        "tickers": tickers,
                        "sources": [slug],
                        "_tickers_n": tickers_n,
                    })

    # strip the internal helper field before returning
    for m in merged:
        m.pop("_tickers_n", None)
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inv_newsletter.digest_v3.route_merge",
        description="Merge per-email routing outputs into route_map.json (deterministic).",
    )
    parser.add_argument("date", help="Target date, e.g. 2026-06-08")
    args = parser.parse_args(argv)

    try:
        payload = build_route_map(args.date)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out_path = _v3_dir(args.date) / "route_map.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {out_path}")
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))

    # ── per-sector slices: one file per content sector with content ──────
    # Resolve image_path from chunks.json so section agents don't open it.
    chunks_path = _v3_dir(args.date) / "chunks.json"
    chunks_doc = json.loads(chunks_path.read_text(encoding="utf-8"))
    image_path_by_id = {
        c["chunk_id"]: c.get("image_path")
        for c in chunks_doc.get("chunks", [])
        if c.get("type") == "image"
    }

    sections_dir = _v3_dir(args.date) / "sections_input"
    sections_dir.mkdir(parents=True, exist_ok=True)
    n_slices = 0
    for sector_name, bucket in payload["sectors"].items():
        slug = SECTOR_SLUGS.get(sector_name)
        if slug is None:
            continue
        images = [
            {
                "img_id": img["img_id"],
                "source_slug": img["source_slug"],
                "caption": img["caption"],
                "image_path": image_path_by_id.get(img["img_id"]),
            }
            for img in bucket["images"]
        ]
        slice_payload = {
            "sector": sector_name,
            "primary": sorted(bucket["primary"], key=_primary_sort_key),
            "secondary": bucket["secondary"],
            "images": images,
        }
        (sections_dir / f"{slug}.json").write_text(
            json.dumps(slice_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        n_slices += 1
    print(f"wrote {n_slices} per-sector slices to sections_input/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
