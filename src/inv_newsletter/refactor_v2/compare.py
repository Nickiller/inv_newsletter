"""Comparison report generator for the A/B experiment.

Compares two daily-digest markdown files across:
  (a) Info density — char count, distinct ticker count, number / percentage / date density
  (b) Link coverage — vs the same link_inventory (rates of preservation)
  (c) Cross-source claims — count of "两家共识 / 多家覆盖 / 卖方分歧" phrases
  (d) Theme grouping anti-pattern — `###` sections with ≤3 body lines
  (e) Per-stage / total cost
  (e2) Importance ordering — extract top-N theme per sector from both, surface
       which themes lead each sector and whether they meet importance criteria
       (multi-source license / mega-cap ticker / contains catalyst keyword)

Output: comparison_report.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .validators import _LINK_RE, _CROSS_SOURCE_PHRASES, _TICKER_RE

_MEGA_CAPS = {"NVDA", "AMZN", "GOOGL", "META", "AAPL", "MSFT", "TSLA"}
_PCT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?%")
_DATE_RE = re.compile(r"\b(?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12][0-9]|3[01])\b")
_DOLLAR_RE = re.compile(r"\$[\d,]+(?:\.\d+)?\s*[KMBT]?")
_HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)
_NON_TICKER = {"AI", "AWS", "GCP", "API", "CPU", "GPU", "HBM", "EPS", "PE", "TAM",
               "JPM", "MS", "GS", "WSJ", "FT", "CNBC", "YOY", "QOQ", "OW", "EW", "PT"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def info_density(text: str) -> dict:
    """Count factual artifacts: numbers, percentages, dates, dollar amounts, tickers."""
    pcts = len(_PCT_RE.findall(text))
    dates = len(_DATE_RE.findall(text))
    dollars = len(_DOLLAR_RE.findall(text))
    tickers = {t for t in _TICKER_RE.findall(text) if t not in _NON_TICKER and len(t) >= 2}
    return {
        "char_count": len(text),
        "distinct_tickers": sorted(tickers),
        "distinct_ticker_count": len(tickers),
        "percentage_count": pcts,
        "date_count": dates,
        "dollar_count": dollars,
        "fact_density_per_kchar": round((pcts + dates + dollars) / max(len(text) / 1000, 1), 2),
    }


def link_stats(text: str, link_inventory: dict) -> dict:
    """How many of the source-inventory sell-side links + anchor traps appear in this digest."""
    digest_urls = {m.group(2) for m in _LINK_RE.finditer(text)}
    entries = link_inventory.get("entries", [])
    sell_side = [e for e in entries if e["category"] == "sell_side"]
    anchor_trap = [e for e in sell_side if e["anchor_trap"]]

    def url_present(e):
        return (e["url"] in digest_urls
                or (e.get("unwrapped_url") and e["unwrapped_url"] in digest_urls))

    sell_side_present = sum(1 for e in sell_side if url_present(e))
    anchor_trap_present = sum(1 for e in anchor_trap if url_present(e))

    return {
        "digest_urls": len(digest_urls),
        "inventory_sell_side": len(sell_side),
        "inventory_anchor_trap": len(anchor_trap),
        "sell_side_preserved": sell_side_present,
        "sell_side_pct": round(100.0 * sell_side_present / len(sell_side), 1) if sell_side else None,
        "anchor_trap_preserved": anchor_trap_present,
        "anchor_trap_pct": round(100.0 * anchor_trap_present / len(anchor_trap), 1) if anchor_trap else None,
    }


def cross_source_claims(text: str) -> dict:
    """Count of cross-source-claim phrases. (Verification vs cross_source happens in validators.py.)"""
    counts = {p: len(re.findall(p, text)) for p in _CROSS_SOURCE_PHRASES}
    return {"total": sum(counts.values()), "by_phrase": {k: v for k, v in counts.items() if v}}


def theme_anti_patterns(text: str, min_body_lines: int = 3) -> dict:
    """Find `###` sections whose body is shorter than min_body_lines."""
    # Split into ### blocks
    blocks = re.split(r"^### ", text, flags=re.MULTILINE)
    # blocks[0] = preamble (no ###); rest start with the title line
    short_themes: list[str] = []
    all_themes: list[str] = []
    for b in blocks[1:]:
        lines = b.splitlines()
        title = lines[0].strip() if lines else ""
        all_themes.append(title)
        # Body = non-empty lines after title, until next ## or end
        body_lines = []
        for l in lines[1:]:
            if l.startswith("## ") or l.startswith("### "):
                break
            if l.strip():
                body_lines.append(l)
        if len(body_lines) < min_body_lines:
            short_themes.append(title)
    return {
        "total_themes": len(all_themes),
        "short_theme_count": len(short_themes),
        "short_themes": short_themes,
    }


def importance_ordering(text: str, cross_source: dict) -> dict:
    """For each sector, list top-3 themes; flag whether top theme meets importance criteria."""
    cross_tickers = set(cross_source.get("cross_source_tickers", {}).keys())
    sectors: list[dict] = []
    current: dict | None = None
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        if level == 2:
            current = {"sector": title, "themes": []}
            sectors.append(current)
        elif level == 3 and current is not None:
            current["themes"].append(title)

    for s in sectors:
        top = s["themes"][:3]
        s["top_themes"] = top
        # Top theme importance check: does the top theme title contain a mega-cap or a cross-source ticker?
        if top:
            top_title = top[0]
            top_tickers = set(_TICKER_RE.findall(top_title)) - _NON_TICKER
            s["top_theme_has_megacap"] = bool(top_tickers & _MEGA_CAPS)
            s["top_theme_has_cross_source_ticker"] = bool(top_tickers & cross_tickers)
            s["top_theme_meets_importance"] = (
                s["top_theme_has_megacap"]
                or s["top_theme_has_cross_source_ticker"]
                or any(kw in top_title for kw in ("财报", "guide", "TAM", "超级周期", "重估", "上调", "下调", "缺口"))
            )
        else:
            s["top_theme_meets_importance"] = None
    return {"sectors": sectors}


def render_report(
    *,
    baseline_path: Path,
    v2_path: Path,
    link_inventory_path: Path,
    cross_source_path: Path,
    cost_ledger_path: Path,
    output_path: Path,
) -> dict:
    baseline = _read_text(baseline_path)
    v2 = _read_text(v2_path)
    link_inventory = json.loads(_read_text(link_inventory_path) or "{}")
    cross_source = json.loads(_read_text(cross_source_path) or "{}")
    cost_ledger = json.loads(_read_text(cost_ledger_path) or "{}")

    b_density = info_density(baseline)
    v_density = info_density(v2)
    b_links = link_stats(baseline, link_inventory)
    v_links = link_stats(v2, link_inventory)
    b_cs = cross_source_claims(baseline)
    v_cs = cross_source_claims(v2)
    b_themes = theme_anti_patterns(baseline)
    v_themes = theme_anti_patterns(v2)
    b_order = importance_ordering(baseline, cross_source)
    v_order = importance_ordering(v2, cross_source)

    lines = ["# Comparison Report — refactor_v2 vs baseline", "",
             f"- Baseline: `{baseline_path}` ({len(baseline):,} chars)",
             f"- v2:       `{v2_path}` ({len(v2):,} chars)",
             ""]

    lines += ["## (a) Info density", "",
              "| metric | baseline | v2 | Δ |",
              "| --- | --- | --- | --- |"]
    def row(label, b_val, v_val, fmt=lambda x: f"{x:,}"):
        if isinstance(b_val, (int, float)) and isinstance(v_val, (int, float)):
            delta = v_val - b_val
            return f"| {label} | {fmt(b_val)} | {fmt(v_val)} | {'+' if delta > 0 else ''}{fmt(delta) if isinstance(delta, (int, float)) else delta} |"
        return f"| {label} | {b_val} | {v_val} | |"
    lines.append(row("char count", b_density["char_count"], v_density["char_count"]))
    lines.append(row("distinct tickers", b_density["distinct_ticker_count"], v_density["distinct_ticker_count"]))
    lines.append(row("`%` count", b_density["percentage_count"], v_density["percentage_count"]))
    lines.append(row("date count", b_density["date_count"], v_density["date_count"]))
    lines.append(row("`$` amount count", b_density["dollar_count"], v_density["dollar_count"]))
    lines.append(row("fact density / kchar", b_density["fact_density_per_kchar"], v_density["fact_density_per_kchar"], fmt=lambda x: f"{x:.2f}"))

    only_v2 = set(v_density["distinct_tickers"]) - set(b_density["distinct_tickers"])
    only_b = set(b_density["distinct_tickers"]) - set(v_density["distinct_tickers"])
    if only_v2:
        lines.append("")
        lines.append(f"**v2 unique tickers**: {', '.join(sorted(only_v2))}")
    if only_b:
        lines.append(f"**baseline unique tickers**: {', '.join(sorted(only_b))}")

    lines += ["", "## (b) Link coverage", "",
              "| metric | baseline | v2 |",
              "| --- | --- | --- |",
              f"| total URLs in digest | {b_links['digest_urls']} | {v_links['digest_urls']} |",
              f"| sell-side preserved (of {b_links['inventory_sell_side']}) | "
              f"{b_links['sell_side_preserved']} ({b_links['sell_side_pct']}%) | "
              f"{v_links['sell_side_preserved']} ({v_links['sell_side_pct']}%) |",
              f"| anchor-trap preserved (of {b_links['inventory_anchor_trap']}) | "
              f"{b_links['anchor_trap_preserved']} ({b_links['anchor_trap_pct']}%) | "
              f"{v_links['anchor_trap_preserved']} ({v_links['anchor_trap_pct']}%) |"]

    lines += ["", "## (c) Cross-source claims", "",
              f"- baseline: **{b_cs['total']}** phrases ({b_cs['by_phrase']})",
              f"- v2:       **{v_cs['total']}** phrases ({v_cs['by_phrase']})",
              "",
              "_Validator-detected suspicious claims for v2 are in `audit_report.md`._"]

    lines += ["", "## (d) Theme grouping anti-pattern (### sections with <3 body lines)", "",
              f"- baseline: **{b_themes['short_theme_count']}** / {b_themes['total_themes']} themes",
              f"- v2:       **{v_themes['short_theme_count']}** / {v_themes['total_themes']} themes"]
    if b_themes["short_themes"]:
        lines.append("\n**baseline short themes**:")
        for t in b_themes["short_themes"]:
            lines.append(f"- `{t}`")
    if v_themes["short_themes"]:
        lines.append("\n**v2 short themes**:")
        for t in v_themes["short_themes"]:
            lines.append(f"- `{t}`")

    lines += ["", "## (e) Per-stage cost (v2 only — baseline cost not tracked here)", ""]
    totals = cost_ledger.get("totals", {})
    by_stage = totals.get("by_stage", {})
    lines.append("| stage | calls | input tok | output tok | duration | cost USD |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for stage, s in by_stage.items():
        lines.append(f"| {stage} | {s['calls']} | {s['in']:,} | {s['out']:,} | {s['duration']}s | ${s['cost']:.4f} |")
    lines.append(f"| **TOTAL** |   | {totals.get('grand_input_tokens', 0):,} | "
                 f"{totals.get('grand_output_tokens', 0):,} |   | "
                 f"**${totals.get('grand_cost_usd', 0):.4f}** |")

    lines += ["", "## Importance ordering — top theme per sector", "",
              "### Baseline"]
    for s in b_order["sectors"]:
        meets = "✓" if s.get("top_theme_meets_importance") else "✗"
        top = s["top_themes"][0] if s["top_themes"] else "(no themes)"
        lines.append(f"- **{s['sector']}** ← {meets} `{top}`")

    lines.append("\n### v2")
    for s in v_order["sectors"]:
        meets = "✓" if s.get("top_theme_meets_importance") else "✗"
        top = s["top_themes"][0] if s["top_themes"] else "(no themes)"
        lines.append(f"- **{s['sector']}** ← {meets} `{top}`")

    lines.append("\n_Mark `✓` means top theme contains a mega-cap, a cross-source-licensed ticker, or a catalyst keyword (财报/guide/TAM/超级周期/...). It is a heuristic, not a definitive judgement._")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "baseline": {"density": b_density, "links": b_links, "cross_source": b_cs,
                     "themes": b_themes, "order": b_order},
        "v2": {"density": v_density, "links": v_links, "cross_source": v_cs,
               "themes": v_themes, "order": v_order},
        "cost": totals,
    }
