"""Post-generation validators (mirrors the existing image-ref validator pattern).

Two checks:
1. Link coverage: which sell-side / anchor-trap URLs from the source emails
   actually made it into the digest. Reports dropped URLs.
2. Cross-source claim accuracy: any digest sentence claiming "两家共识 /
   多家覆盖 / 卖方分歧" near a ticker is validated against the cross_source
   packet — must reference a ticker / theme with ≥2 sources.

Each validator returns warnings; warnings are aggregated into audit_report.md.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_CROSS_SOURCE_PHRASES = [
    "两家共识", "两家均", "多家覆盖", "卖方分歧", "多源共识", "多源覆盖",
    "三家", "数家", "多家研报", "卖方共识",
]
_TICKER_RE = re.compile(r"\b([A-Z]{2,6})\b")


def _digest_urls(digest_text: str) -> list[tuple[str, str]]:
    """Return list of (anchor_text, url) tuples in the digest."""
    return [(m.group(1), m.group(2)) for m in _LINK_RE.finditer(digest_text)]


def _url_overlap(digest_url: str, inv_url: str, inv_unwrapped: str | None) -> bool:
    """Check if a digest URL matches an inventory URL (loose match — host + path prefix)."""
    candidates = [inv_url] + ([inv_unwrapped] if inv_unwrapped else [])
    digest_parsed = urlparse(digest_url)
    for c in candidates:
        cp = urlparse(c)
        if digest_parsed.netloc == cp.netloc and digest_parsed.path[:60] == cp.path[:60]:
            return True
    return False


def validate_link_coverage(digest_text: str, link_inventory: dict) -> dict:
    """Compare digest URLs against link_inventory; flag dropped sell-side / anchor-trap URLs."""
    digest_urls = _digest_urls(digest_text)
    digest_url_set = {u for _, u in digest_urls}

    sell_side_entries = [e for e in link_inventory.get("entries", []) if e["category"] == "sell_side"]
    anchor_trap_entries = [e for e in sell_side_entries if e["anchor_trap"]]

    sell_side_present = 0
    sell_side_dropped: list[dict] = []
    for e in sell_side_entries:
        # Check if either the wrapper URL or the unwrapped URL appears in digest
        present = (
            e["url"] in digest_url_set
            or (e.get("unwrapped_url") and e["unwrapped_url"] in digest_url_set)
            or any(_url_overlap(u, e["url"], e.get("unwrapped_url")) for u in digest_url_set)
        )
        if present:
            sell_side_present += 1
        else:
            sell_side_dropped.append(e)

    anchor_trap_present = sum(
        1 for e in anchor_trap_entries
        if (e["url"] in digest_url_set
            or (e.get("unwrapped_url") and e["unwrapped_url"] in digest_url_set)
            or any(_url_overlap(u, e["url"], e.get("unwrapped_url")) for u in digest_url_set))
    )

    return {
        "digest_url_count": len(digest_url_set),
        "inventory_sell_side_count": len(sell_side_entries),
        "inventory_anchor_trap_count": len(anchor_trap_entries),
        "sell_side_preserved": sell_side_present,
        "sell_side_coverage_pct": round(100.0 * sell_side_present / len(sell_side_entries), 1) if sell_side_entries else None,
        "anchor_trap_preserved": anchor_trap_present,
        "anchor_trap_coverage_pct": round(100.0 * anchor_trap_present / len(anchor_trap_entries), 1) if anchor_trap_entries else None,
        "dropped": [
            {
                "subject": e["email_subject"][:60],
                "anchor": e["anchor_text"],
                "host": e["subcategory"],
                "url": (e.get("unwrapped_url") or e["url"])[:100],
                "anchor_trap": e["anchor_trap"],
            }
            for e in sell_side_dropped
        ],
    }


def validate_cross_source_claims(digest_text: str, cross_source: dict, lookback_chars: int = 80) -> dict:
    """Find sentences making cross-source claims; verify against cross_source packet.

    Looks for cross-source phrase, then scans nearby chars for tickers.
    If a ticker is mentioned near the claim, check it appears in cross_source_tickers.
    Returns list of suspicious claims (could not verify).
    """
    cross_tickers = set(cross_source.get("cross_source_tickers", {}).keys())
    suspicious: list[dict] = []

    for phrase in _CROSS_SOURCE_PHRASES:
        for m in re.finditer(phrase, digest_text):
            start = max(0, m.start() - lookback_chars)
            end = min(len(digest_text), m.end() + lookback_chars)
            context = digest_text[start:end]
            tickers_nearby = set(_TICKER_RE.findall(context))
            # Filter common non-ticker words (subset)
            tickers_nearby = {t for t in tickers_nearby if t not in {
                "AI", "JPM", "MS", "GS", "AWS", "GCP", "API", "CPU", "GPU",
                "USD", "CNY", "EUR", "WSJ", "FT", "EPS", "PE", "TAM",
            } and len(t) >= 2}
            if not tickers_nearby:
                continue
            unsupported = tickers_nearby - cross_tickers
            if unsupported:
                suspicious.append({
                    "phrase": phrase,
                    "context": context.replace("\n", " ").strip(),
                    "tickers_in_context": sorted(tickers_nearby),
                    "unsupported_tickers": sorted(unsupported),
                })

    return {
        "claim_count": sum(len(re.findall(p, digest_text)) for p in _CROSS_SOURCE_PHRASES),
        "suspicious_count": len(suspicious),
        "suspicious": suspicious,
    }


def write_audit_report(
    *,
    digest_text: str,
    link_inventory: dict,
    cross_source: dict,
    audit_path,
) -> dict:
    """Run both validators; write audit_report.md; return combined dict."""
    link_report = validate_link_coverage(digest_text, link_inventory)
    cs_report = validate_cross_source_claims(digest_text, cross_source)

    lines = ["# Audit Report — refactor_v2", "",
             "Automated post-generation validation. Warnings here do NOT mean the digest is wrong —",
             "they flag claims/links worth human review.",
             "",
             "## 1. Link coverage",
             "",
             f"- Digest contains **{link_report['digest_url_count']}** distinct URLs",
             f"- Inventory sell-side links: **{link_report['inventory_sell_side_count']}**",
             f"- Sell-side preserved: **{link_report['sell_side_preserved']}** "
             f"({link_report['sell_side_coverage_pct']}%)",
             f"- Anchor-trap (`[notes]`/`[here]`/`[link]`) preserved: "
             f"**{link_report['anchor_trap_preserved']}** / "
             f"{link_report['inventory_anchor_trap_count']} "
             f"({link_report['anchor_trap_coverage_pct']}%)",
             ""]
    if link_report["dropped"]:
        lines.append("### ⚠️ Dropped sell-side links")
        lines.append("")
        for d in link_report["dropped"][:50]:
            trap = " 🪤" if d["anchor_trap"] else ""
            lines.append(f"- `[{d['anchor']}]` `{d['host']}`{trap} — `{d['subject']}`")
            lines.append(f"  {d['url']}")
        if len(link_report["dropped"]) > 50:
            lines.append(f"\n_({len(link_report['dropped']) - 50} more dropped, truncated)_")
    else:
        lines.append("### ✅ No sell-side links dropped")
    lines.extend(["", "## 2. Cross-source claim accuracy", "",
                  f"- Total `两家共识 / 多家覆盖 / 卖方分歧 / ...` phrases in digest: **{cs_report['claim_count']}**",
                  f"- Suspicious (claims tickers not in cross_source license): **{cs_report['suspicious_count']}**", ""])
    if cs_report["suspicious"]:
        lines.append("### ⚠️ Unverified cross-source claims")
        lines.append("")
        for s in cs_report["suspicious"]:
            lines.append(f"- **phrase**: `{s['phrase']}` near tickers `{', '.join(s['unsupported_tickers'])}`")
            lines.append(f"  context: _{s['context'][:200]}..._")
    else:
        lines.append("### ✅ No unverified cross-source claims detected")

    audit_path.write_text("\n".join(lines), encoding="utf-8")
    return {"link_coverage": link_report, "cross_source_claims": cs_report}
