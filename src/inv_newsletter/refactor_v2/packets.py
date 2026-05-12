"""Normalized packet builders for refactor_v2 pipeline.

Produces JSON packets + human-readable helper markdown files that ground
Stage B drafting in pre-extracted facts rather than letting the LLM re-aggregate
from raw email bodies.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


# ---------- Link inventory --------------------------------------------------

_SELL_SIDE_HOSTS = {
    "jefferies": ("jefferies.email.streetcontxt.net", "jefferies.com", "javatar.bluematrix.com"),
    "jpm": ("jpmorgan.email.streetcontxt.net", "markets.jpmorgan.com", "morganmarkets.com", "jpmm.com", "jpmorgan.com", "jpmorgan.co.jp"),
    "bernstein": ("bernstein.email.streetcontxt.net", "bernsteinresearch.com", "bernsteinsg.com"),
    "wolfe": ("wolferesearch.com", "wolfe.streetcontxt.net"),
    "ms": ("morganstanley.com", "ms.streetcontxt.net"),
    "gs": ("goldmansachs.com", "gs.streetcontxt.net"),
}

_NEWS_HOSTS = {
    "wsj.com", "bloomberg.com", "cnbc.com", "reuters.com", "ft.com",
    "digitimes.com", "theregister.com", "businesswire.com", "prnewswire.com",
    "techcrunch.com", "theverge.com", "axios.com", "nytimes.com",
    "oregonlive.com",
}

_SOCIAL_HOSTS = {"x.com", "twitter.com", "youtube.com", "youtu.be"}

_BLOG_HOSTS = {"substack.com", "etnalabs.co", "semianalysis.com", "fundaai.com"}

_MERITCO_HOST = "research.meritco-group.com"

# Anchor text patterns that often hide sell-side report links
_ANCHOR_TRAP_WORDS = {"notes", "here", "link", "report", "preview", "piece", "更多", "details", "read", "click"}

_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def _classify_url(url: str) -> tuple[str, str]:
    """Return (category, subcategory). category ∈ sell_side|news|social|blog|meritco|company_ir|other."""
    host = urlparse(url).netloc.lower()
    for desk, hosts in _SELL_SIDE_HOSTS.items():
        if any(h in host for h in hosts):
            return ("sell_side", desk)
    if host == _MERITCO_HOST:
        return ("meritco", "meritco")
    if any(host.endswith(h) for h in _NEWS_HOSTS):
        return ("news", host)
    if any(host.endswith(h) for h in _SOCIAL_HOSTS):
        return ("social", host)
    if any(h in host for h in _BLOG_HOSTS):
        return ("blog", host)
    return ("other", host)


def _unwrap_streetcontxt(url: str) -> str | None:
    """Sell-side wrapper streetcontxt.net carries true target in ?url= param.

    Returns the underlying URL if present, else None.
    """
    parsed = urlparse(url)
    if "streetcontxt.net" not in parsed.netloc:
        return None
    qs = parse_qs(parsed.query)
    target = qs.get("url")
    return target[0] if target else None


def build_link_inventory(emails: list[dict], output_path: Path) -> dict:
    """Scan email bodies for markdown links, classify, return inventory.

    Each entry: {
      email_idx, email_subject, anchor_text, url,
      unwrapped_url (if streetcontxt wrapper),
      category, subcategory, anchor_trap (bool)
    }
    """
    entries: list[dict] = []
    for idx, email in enumerate(emails):
        subject = email["frontmatter"].get("subject", "?")
        body = email.get("body", "")
        for m in _LINK_RE.finditer(body):
            anchor = m.group(1).strip()
            url = m.group(2).strip()
            unwrapped = _unwrap_streetcontxt(url)
            url_to_classify = unwrapped or url
            category, subcategory = _classify_url(url_to_classify)
            # Anchor trap: short generic anchor + sell-side wrapper → likely a hidden research link
            anchor_lower = anchor.lower()
            anchor_trap = (
                category == "sell_side"
                and (len(anchor) <= 12 or anchor_lower in _ANCHOR_TRAP_WORDS)
            )
            entries.append({
                "email_idx": idx,
                "email_subject": subject,
                "anchor_text": anchor,
                "url": url,
                "unwrapped_url": unwrapped,
                "category": category,
                "subcategory": subcategory,
                "anchor_trap": anchor_trap,
            })

    inventory = {
        "total_links": len(entries),
        "by_category": _count_by(entries, "category"),
        "sell_side_count": sum(1 for e in entries if e["category"] == "sell_side"),
        "anchor_trap_count": sum(1 for e in entries if e["anchor_trap"]),
        "entries": entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    return inventory


def write_link_helper(inventory: dict, helper_path: Path) -> None:
    """Human-readable summary of link inventory, grouped by email then category."""
    lines = ["# Link Inventory Helper", "",
             f"Total links: **{inventory['total_links']}** "
             f"(sell-side: {inventory['sell_side_count']}, "
             f"anchor traps: {inventory['anchor_trap_count']})", ""]
    lines.append("## By category")
    for cat, n in inventory["by_category"].items():
        lines.append(f"- `{cat}`: {n}")
    lines.append("")
    lines.append("## ⚠️ Anchor-trap candidates (短锚文本 + sell-side wrapper)")
    lines.append("")
    lines.append("These are the most likely-to-be-dropped sell-side research links.")
    lines.append("Stage B drafting MUST preserve these where the content is referenced.")
    lines.append("")
    for e in inventory["entries"]:
        if e["anchor_trap"]:
            lines.append(f"- `{e['email_subject'][:50]}` — `[{e['anchor_text']}]` → `{e['subcategory']}`")
            lines.append(f"  url: {e['url'][:100]}...")
    lines.append("")
    lines.append("## All sell-side links by email")
    by_email: dict[int, list[dict]] = defaultdict(list)
    for e in inventory["entries"]:
        if e["category"] == "sell_side":
            by_email[e["email_idx"]].append(e)
    for idx, items in sorted(by_email.items()):
        if not items:
            continue
        lines.append(f"\n### 邮件 #{idx + 1}: {items[0]['email_subject'][:60]}")
        for e in items:
            target = e["unwrapped_url"] or e["url"]
            lines.append(f"- [{e['anchor_text']}]({target[:80]}...) — `{e['subcategory']}`")
    helper_path.write_text("\n".join(lines), encoding="utf-8")


# ---------- Delta (vs prior day) --------------------------------------------

_HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)
_TICKER_RE = re.compile(r"\b([A-Z]{2,6})\b")
_NON_TICKER_WORDS = {
    "AI", "AWS", "GCP", "API", "CPU", "GPU", "HBM", "LTA", "PT", "GM", "EPS",
    "FX", "EV", "EBIT", "FCF", "OPEX", "CAPEX", "TAM", "SAM", "NRR", "CRPO",
    "RPO", "MAU", "DAU", "PE", "DCF", "PM", "VP", "CEO", "CFO", "CTO", "CIO",
    "USD", "CNY", "EUR", "JPY", "GBP", "QOQ", "YOY", "FY", "CY", "ESG",
    "ROIC", "ROIC", "WACC", "IPO", "M&A", "VC", "PE", "LP", "GP", "IC",
    "TMT", "ETF", "REIT", "GAAP", "SEC", "SEC", "FED", "ECB", "BOJ",
    "IT", "OT", "HR", "PR", "IR", "CRM", "ERP", "SCM", "BPO",
    "SOTP", "DD", "QC", "QA", "ASIC", "FPGA", "DRAM", "NAND", "SSD",
    "PCIE", "USB", "HDMI", "LCD", "OLED", "LED",
    "PE", "PB", "PS", "PEG", "PSR",
    "BUY", "SELL", "HOLD", "OW", "EW", "UW", "NA", "TBD",
    "JPM", "MS", "GS", "WFC", "BAC", "C", "BBG", "WSJ", "FT", "CNBC",
}


def build_delta_packet(prior_day_digest_path: Path, output_path: Path) -> dict:
    """Parse prior day's digest. Extract section headings + likely tickers.

    Used by Stage A triage to flag is_followup_of_prior_day per theme.
    """
    if not prior_day_digest_path.exists():
        packet = {"prior_day_exists": False, "prior_day_path": str(prior_day_digest_path),
                  "sections": [], "tickers": []}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        return packet

    text = prior_day_digest_path.read_text(encoding="utf-8")
    sections: list[dict] = []
    current_sector: str | None = None
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        if level == 2:
            current_sector = title
            sections.append({"sector": title, "themes": []})
        elif level == 3 and sections:
            sections[-1]["themes"].append(title)

    # Naive ticker extraction: ALL-CAPS 2-6 chars, excluded common acronyms
    candidate_tickers = set(_TICKER_RE.findall(text))
    tickers = sorted(t for t in candidate_tickers if t not in _NON_TICKER_WORDS and len(t) >= 2)

    packet = {
        "prior_day_exists": True,
        "prior_day_path": str(prior_day_digest_path),
        "sections": sections,
        "tickers": tickers,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    return packet


def write_delta_helper(delta: dict, helper_path: Path) -> None:
    if not delta.get("prior_day_exists"):
        helper_path.write_text("# Delta Helper\n\n_No prior-day digest found._\n", encoding="utf-8")
        return
    lines = ["# Delta Helper — vs prior day", "",
             f"Prior day digest: `{delta['prior_day_path']}`", "",
             "## 昨日板块与主题"]
    for s in delta["sections"]:
        lines.append(f"\n### {s['sector']}")
        for t in s["themes"]:
            lines.append(f"- {t}")
    lines.append("")
    lines.append("## 昨日出现的 Ticker（用于 follow-up 判定）")
    lines.append("")
    lines.append(", ".join(f"`{t}`" for t in delta["tickers"]))
    lines.append("")
    lines.append("**Stage A triage 提示**：如果今日某主题与昨日的主题/Ticker 高度重合，且**无新事件**（仅 tracking），")
    lines.append("应在 triage.json 标 `is_followup_of_prior_day=true`，Stage B 起草时可缩短为 1-2 行或并入简短跟踪。")
    helper_path.write_text("\n".join(lines), encoding="utf-8")


# ---------- Cross-source (from triage) --------------------------------------

def build_cross_source_from_triage(triage: dict, output_path: Path) -> dict:
    """Aggregate triage by ticker → list of sources. Flag tickers with ≥2 distinct sources.

    Same for themes. Assumes triage schema has sectors[].themes[].tickers[]
    and theme.sources[].
    """
    ticker_sources: dict[str, set[str]] = defaultdict(set)
    theme_sources: dict[str, set[str]] = defaultdict(set)

    for sector in triage.get("sectors", []):
        for theme in sector.get("themes", []):
            srcs = set(theme.get("sources", []))
            theme_key = f"{sector['name']} / {theme['name']}"
            theme_sources[theme_key].update(srcs)
            for ticker in theme.get("tickers", []):
                tk = ticker if isinstance(ticker, str) else ticker.get("symbol", "")
                if tk:
                    ticker_sources[tk].update(srcs)

    cross_tickers = {t: sorted(s) for t, s in ticker_sources.items() if len(s) >= 2}
    cross_themes = {th: sorted(s) for th, s in theme_sources.items() if len(s) >= 2}

    packet = {
        "cross_source_tickers": cross_tickers,
        "cross_source_themes": cross_themes,
        "single_source_tickers": {t: sorted(s) for t, s in ticker_sources.items() if len(s) == 1},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    return packet


def write_cross_source_helper(cs: dict, helper_path: Path) -> None:
    lines = ["# Cross-Source Helper", "",
             "Stage B 起草时**只有**列在这里的 ticker / 主题才能写 `两家共识` / `多家覆盖` / `卖方分歧`。",
             "Stage C validator 会核对这些声明，错误标记会写到 audit_report.md。", "",
             "## 跨源主题（≥2 源覆盖）"]
    if not cs["cross_source_themes"]:
        lines.append("_本日无跨源主题。_")
    else:
        for theme, sources in cs["cross_source_themes"].items():
            lines.append(f"- **{theme}** ← {', '.join(sources)}")
    lines.append("")
    lines.append("## 跨源 Ticker（≥2 源覆盖）")
    if not cs["cross_source_tickers"]:
        lines.append("_本日无跨源 Ticker。_")
    else:
        for ticker, sources in sorted(cs["cross_source_tickers"].items()):
            lines.append(f"- **{ticker}** ← {', '.join(sources)}")
    lines.append("")
    lines.append("## 单源 Ticker（仅 1 源覆盖，写作时**不要**声明 cross-source）")
    if not cs["single_source_tickers"]:
        lines.append("_无_")
    else:
        for ticker, sources in sorted(cs["single_source_tickers"].items()):
            lines.append(f"- {ticker} ← {sources[0]}")
    helper_path.write_text("\n".join(lines), encoding="utf-8")


# ---------- Utilities -------------------------------------------------------

def _count_by(entries: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for e in entries:
        out[e[key]] += 1
    return dict(out)
