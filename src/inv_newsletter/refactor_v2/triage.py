"""Stage A: Triage.

Cluster the day's emails + meritco minutes into the fixed sector list, identify
themes within each sector, rank by importance, surface cross-source / single-source
distinctions, and flag follow-ups vs prior day.

Output: triage.json with schema:
{
  "sectors": [
    {
      "name": "半导体与硬件",
      "themes": [
        {
          "name": "存储超级周期 + LTA 重估",
          "importance_score": 9,
          "importance_reason": "多源覆盖 (JPM+Jefferies+久谦)，mega-cap MU，guidance change",
          "sources": ["jpm_chips_breakfast", "jefferies_tech", "meritco-3114"],
          "tickers": ["MU", "SK Hynix", "WDC", "兆易创新"],
          "is_followup_of_prior_day": true
        }
      ],
      "short_tracking": [
        {"text": "MCHP 涨价滞后", "source": "jefferies_tech"}
      ]
    }
  ]
}
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import anthropic

from .compose import load_contract
from .cost import CostLedger

logger = logging.getLogger(__name__)


TRIAGE_SYSTEM = """\
You are a senior buyside research analyst performing triage on the day's investment research emails.

Your job: cluster all content into the fixed sector list, identify themes within each sector,
rank themes by importance (highest first), and produce a structured JSON outline.

Importance criteria for ranking (any one promotes a theme up):
- Multi-source coverage (≥2 sell-side desks or sell-side + 久谦 expert call)
- Mega-cap involvement (NVDA, AMZN, GOOGL, META, AAPL, MSFT, TSLA)
- Earnings event / guidance change / new product launch on the trading day
- Stock move ±5% or more
- New thesis / first-time information vs prior knowledge

You MUST produce themes in DESCENDING order of importance within each sector.
You MUST distinguish multi-source themes from single-source 简短跟踪 items.
Items that are single-source AND short AND have no new event go in short_tracking, not as a theme.

Be CONCISE in the JSON output:
- theme `name` ≤ 40 chars
- `importance_reason` ≤ 80 chars (just the trigger criterion, e.g., "multi-source + earnings event")
- Output STRICT JSON only — no prose before or after the JSON block, no markdown code fences
"""


TRIAGE_USER_TEMPLATE = """\
## Fixed sector list (use these names verbatim, AI first, 其他 last)
{sectors}

## Importance criteria refresher
- Multi-source (≥2 desks or sell-side + 久谦) → high
- Mega-cap (NVDA, AMZN, GOOGL, META, AAPL, MSFT, TSLA) → high
- Earnings / guidance change / launch event → high
- Stock ±5% → high
- New thesis → high
- Otherwise single-source tracking → low (goes in short_tracking)

## Short-theme merge rule
A theme that has ≤3 lines of substance OR only one single-source single-event item is NOT a theme.
Such items go in `short_tracking[]` for that sector, OR are merged into the most relevant theme as a bullet.

## Read-through routing
A piece of information goes in the sector it AFFECTS, not the sector of its source:
- TSLA Robotaxi → 互联网与数字广告 (affects UBER/LYFT/Waymo)
- NVDA invests in GLW → 半导体 APH段 (affects APH bear narrative)
- DRAM ETF volume → 半导体 存储主题 (memory sentiment)
- 久谦 robotics/biotech → 其他 sector

## Prior-day context (for is_followup_of_prior_day flag)
{prior_day_context}

## Today's sources
{sources_block}

## Required output schema
```json
{{
  "sectors": [
    {{
      "name": "<sector name from list>",
      "themes": [
        {{
          "name": "<theme title>",
          "importance_score": <int 1-10>,
          "importance_reason": "<which criteria>",
          "sources": ["<source_id1>", "<source_id2>"],
          "tickers": ["<TICKER1>", "<TICKER2>"],
          "is_followup_of_prior_day": <bool>
        }}
      ],
      "short_tracking": [
        {{"text": "<one-line>", "source": "<source_id>"}}
      ]
    }}
  ]
}}
```

Rules for output:
- Themes WITHIN a sector must be sorted by importance_score DESC
- Sectors in the fixed order (AI first, 其他 last)
- If a sector has no content, OMIT it entirely (do not include with empty themes)
- source_id values must match the source_id values shown in the sources block
- Output only the JSON object, no prose wrapper, no markdown code fences
"""


def _source_id(email: dict, idx: int) -> str:
    """Stable, human-readable source ID from email frontmatter."""
    fm = email["frontmatter"]
    sender = fm.get("sender_address", "?")
    # Use email subject's first identifying word + sender domain
    if "jefferies" in sender:
        if "While You Were Sleeping" in fm.get("subject", ""):
            return f"jefferies_wyws"
        if "Sketch" in fm.get("subject", ""):
            return f"jpm_tech_sketch"  # JPM-fw via etnalabs
        return "jefferies_tech"
    if "jpmorgan" in sender:
        if "Tech Sketch" in fm.get("subject", "") or "TECH SKETCH" in fm.get("subject", ""):
            return "jpm_tech_sketch"
    if "bernsteinsg" in sender or "bernstein" in sender.lower():
        return "bernstein_tmt"
    if "etnalabs" in sender:
        subj = fm.get("subject", "")
        if "Chips for Breakfast" in subj:
            return f"jpm_chips_breakfast_{idx}"
        if "While You Were Sleeping" in subj:
            return "jefferies_wyws"
        if "Tech HW" in subj:
            return "jpm_tech_hw_semis"
        return f"etnalabs_{idx}"
    if "wolferesearch" in sender:
        return "wolfe_internet"
    if "alphaholic" in sender:
        return "fomo_therapy"
    if "follow-builders" in sender:
        return "ai_builders_digest"
    # Fallback: sanitized subject prefix
    subj_slug = re.sub(r"[^a-z0-9]+", "_", fm.get("subject", f"src{idx}").lower())[:30]
    return subj_slug


def build_sources_block(emails: list[dict], meritco_entries: list[dict]) -> tuple[str, dict[str, dict]]:
    """Render the sources block for triage prompt + return id→source map."""
    source_map: dict[str, dict] = {}
    lines: list[str] = []
    for idx, email in enumerate(emails):
        fm = email["frontmatter"]
        sid = _source_id(email, idx)
        # Deduplicate source IDs (e.g., two JPM Chips fwd)
        suffix = 1
        base = sid
        while sid in source_map:
            sid = f"{base}_{suffix}"
            suffix += 1
        source_map[sid] = {"kind": "email", "email": email, "idx": idx}
        lines.append(f"\n--- source_id: `{sid}` (email) ---")
        lines.append(f"subject: {fm.get('subject', '?')}")
        lines.append(f"sender: {fm.get('sender_name', '?')} <{fm.get('sender_address', '?')}>")
        lines.append(f"received: {fm.get('received_at', '?')}")
        lines.append("")
        lines.append(email.get("body", ""))

    for j, m in enumerate(meritco_entries):
        fm = m["frontmatter"]
        sid = f"meritco_{fm.get('id', f'unknown_{j}')}"
        source_map[sid] = {"kind": "meritco", "entry": m, "idx": j}
        lines.append(f"\n--- source_id: `{sid}` (meritco) ---")
        lines.append(f"date: {m.get('date', '?')}")
        lines.append(f"industry: {fm.get('industry', '?')}")
        lines.append(f"tickers: {fm.get('tickers', [])}")
        lines.append(f"title: {fm.get('subject', '?')}")
        lines.append(f"source_url: {m.get('source_url', '?')}")
        lines.append("")
        lines.append(m.get("body", ""))

    return "\n".join(lines), source_map


def build_prior_day_context(delta: dict) -> str:
    if not delta.get("prior_day_exists"):
        return "_No prior-day digest found. Cannot flag follow-ups._"
    lines = ["Prior-day sectors and themes:"]
    for s in delta["sections"]:
        lines.append(f"\n[{s['sector']}]")
        for t in s["themes"]:
            lines.append(f"  - {t}")
    return "\n".join(lines)


def run_triage(
    *,
    client: anthropic.Anthropic,
    model: str,
    sectors: list[str],
    emails: list[dict],
    meritco_entries: list[dict],
    delta: dict,
    output_path: Path,
    ledger: CostLedger,
    max_tokens: int = 16000,
) -> tuple[dict, dict[str, dict]]:
    """Execute Stage A. Returns (triage_dict, source_id_map)."""
    sources_block, source_map = build_sources_block(emails, meritco_entries)
    prior_day_context = build_prior_day_context(delta)
    sectors_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sectors))

    user_msg = TRIAGE_USER_TEMPLATE.format(
        sectors=sectors_text,
        prior_day_context=prior_day_context,
        sources_block=sources_block,
    )

    logger.info(f"Stage A triage: calling {model}, sources={len(source_map)}, "
                f"input_chars={len(user_msg):,}")
    t0 = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": TRIAGE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    duration = time.perf_counter() - t0
    ledger.record(stage="stage_a_triage", model=model, usage=response.usage,
                  duration_sec=duration,
                  note=f"sources={len(source_map)}, stop={response.stop_reason}")

    raw_text = response.content[0].text.strip()
    # Persist raw response so parse failures can be inspected
    raw_path = output_path.with_suffix(".raw.txt")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw_text, encoding="utf-8")
    if response.stop_reason == "max_tokens":
        logger.warning(
            f"Stage A hit max_tokens={max_tokens}. JSON likely truncated. "
            f"Raw response saved to {raw_path}"
        )
    triage = _parse_triage_json(raw_text)

    # Persist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(triage, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Stage A complete in {duration:.1f}s, "
                f"{response.usage.input_tokens:,}→{response.usage.output_tokens:,} tokens, "
                f"{len(triage.get('sectors', []))} sectors")
    return triage, source_map


def _parse_triage_json(raw: str) -> dict:
    """Robust JSON extraction — handles models that wrap in markdown fences."""
    # Strip ``` fences if present
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1)
    # Find first { ... last } slice
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"Stage A response did not contain valid JSON: {raw[:300]}")
    return json.loads(raw[start:end + 1])


def write_triage_helper(triage: dict, helper_path: Path) -> None:
    """Human-readable view of triage outline."""
    lines = ["# Triage Helper — Stage A Outline", "",
             "Stage B 起草时**严格按此顺序与分类写**，不要重新排序，不要新增/删除主题。", ""]
    for sector in triage.get("sectors", []):
        lines.append(f"## {sector['name']}")
        themes = sector.get("themes", [])
        if not themes:
            lines.append("_(本板块无 ### 主题)_\n")
        for i, t in enumerate(themes, 1):
            followup_tag = " 🔁续日" if t.get("is_followup_of_prior_day") else ""
            lines.append(f"\n### {i}. {t['name']} (score {t['importance_score']}){followup_tag}")
            lines.append(f"- **重要性依据**: {t.get('importance_reason', '?')}")
            lines.append(f"- **来源**: {', '.join(t.get('sources', []))}")
            if t.get("tickers"):
                lines.append(f"- **涉及 Ticker**: {', '.join(t['tickers'])}")
            if t.get("key_facts"):
                lines.append(f"- **关键事实**:")
                for f in t["key_facts"]:
                    lines.append(f"  - {f}")
        short = sector.get("short_tracking", [])
        if short:
            lines.append(f"\n### 简短跟踪")
            for item in short:
                lines.append(f"- {item['text']} *({item.get('source', '?')})*")
        lines.append("")
    helper_path.write_text("\n".join(lines), encoding="utf-8")
