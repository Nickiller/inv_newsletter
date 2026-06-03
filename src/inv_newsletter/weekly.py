"""Weekly investment digest: Meritco-by-ticker + sell-side weeklies + daily-digest cross-check.

Pipeline:
  1. Fetch this week's weekly-summary emails per `weekly_filters` (Mon..Sun window).
  2. Aggregate Meritco minutes for the same week (data/meritco/<date>/*.md).
  3. Pull this week's daily digests from output/daily/<date>_daily_digest.md.
  4. Call Claude with a weekly-specific prompt that:
       - Groups Meritco by ticker, attaches source URL (best-guess forumDetail pattern),
         skips healthcare industries.
       - Summarizes sell-side weeklies (Bernstein Weekly Tech Check, Zukin, etc.).
       - Cross-references signals against this week's daily digests
         (confirm / falsify / new development).
  5. Write digest to output/weekly/<sunday>_weekly_digest.md
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
import yaml

logger = logging.getLogger(__name__)

# Meritco source URL template — best-guess pattern; the front-end accepts both
# `/forum/forumDetail/<id>?forumType=2` and `/forum?forumType=2&forumId=<id>`.
# We use the latter because the user-facing list page lives at /forum?forumType=2.
MERITCO_URL_TEMPLATE = "https://research.meritco-group.com/forum?forumType=2&forumId={id}"

EXCLUDED_INDUSTRY_KEYWORDS = ["医疗", "医药", "健康"]

_PROMPTS_DIR = Path(__file__).parent / "prompts"
WEEKLY_SYSTEM_PROMPT = (_PROMPTS_DIR / "weekly_system.md").read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _week_dates(week_end: date) -> list[date]:
    """Return Mon..Sun dates for the ISO week containing week_end."""
    # Find Monday of week_end
    monday = week_end - timedelta(days=week_end.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


def _meritco_id_to_url(meritco_id: str) -> str | None:
    """meritco-3114 → https://research.meritco-group.com/forum?forumType=2&forumId=3114"""
    m = re.search(r"(\d+)", str(meritco_id or ""))
    if not m:
        return None
    return MERITCO_URL_TEMPLATE.format(id=m.group(1))


def _is_excluded_industry(industry: str) -> bool:
    return any(kw in (industry or "") for kw in EXCLUDED_INDUSTRY_KEYWORDS)


def _load_meritco_week(meritco_dir: Path, week_dates: list[date]) -> list[dict]:
    """Load all meritco minute markdown files within the week (skip healthcare)."""
    out: list[dict] = []
    for d in week_dates:
        date_dir = meritco_dir / d.isoformat()
        if not date_dir.exists():
            continue
        # New filename pattern: YYMMDD_{Tickers}_{Topic}.md, no _meritco_ infix
        for md_file in sorted(date_dir.glob("*.md")):
            try:
                fm, body = _parse_frontmatter(md_file.read_text(encoding="utf-8"))
                if _is_excluded_industry(fm.get("industry", "")):
                    continue
                source_url = _meritco_id_to_url(fm.get("id", ""))
                out.append({
                    "date": d.isoformat(),
                    "frontmatter": fm,
                    "body": body,
                    "source_url": source_url,
                    "filename": md_file.name,
                })
            except Exception as e:
                logger.warning(f"Failed to load meritco file {md_file}: {e}")
    return out


def _load_weekly_emails(mail_dir: Path, week_dates: list[date], weekly_senders: set[str]) -> list[dict]:
    """Load this week's emails whose sender_address is in weekly_senders."""
    out: list[dict] = []
    for d in week_dates:
        date_dir = mail_dir / d.isoformat()
        if not date_dir.exists():
            continue
        for email_md in sorted(date_dir.glob("*/email.md")):
            try:
                raw = email_md.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(raw)
                if fm.get("sender_address", "").lower() not in weekly_senders:
                    continue
                out.append({
                    "date": d.isoformat(),
                    "frontmatter": fm,
                    "body": body,
                    "filename": str(email_md),
                })
            except Exception as e:
                logger.warning(f"Failed to load email {email_md}: {e}")
    return out


def _load_daily_digests(daily_dir: Path, week_dates: list[date]) -> list[dict]:
    """Load this week's daily digest .md files."""
    out: list[dict] = []
    for d in week_dates:
        path = daily_dir / f"{d.isoformat()}_daily_digest.md"
        if not path.exists():
            continue
        try:
            out.append({
                "date": d.isoformat(),
                "body": path.read_text(encoding="utf-8"),
            })
        except Exception as e:
            logger.warning(f"Failed to load daily digest {path}: {e}")
    return out


# ---------------------------------------------------------------------------
# Build LLM input
# ---------------------------------------------------------------------------

_WEEKDAY_CN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _next_week_weekday_table(week_end: date) -> str:
    """Build a Mon..Sun reference for the week AFTER week_end.

    Injected at the top of the user message so the LLM doesn't have to
    compute weekdays itself — it just copies from this table when filling
    Section 6's catalyst calendar.
    """
    next_mon = week_end + timedelta(days=1)
    pairs = []
    for i in range(7):
        d = next_mon + timedelta(days=i)
        pairs.append(f"{d.strftime('%-m/%-d')}={_WEEKDAY_CN[d.weekday()]}")
    return ", ".join(pairs)


def _build_user_text(
    meritco: list[dict],
    weekly_emails: list[dict],
    daily_digests: list[dict],
    week_start: date,
    week_end: date,
) -> str:
    parts: list[str] = []
    parts.append(
        f"# 输入数据 — Week {week_start.isoformat()} → {week_end.isoformat()}\n"
        f"久谦纪要 {len(meritco)} 条 | 卖方周报 {len(weekly_emails)} 封 | "
        f"本周 daily digest {len(daily_digests)} 篇\n"
    )
    parts.append(
        f"\n## 下周日期 → weekday 对照表（Section 6 的 Catalysts Calendar 必须照抄此表，不要自行推算）\n"
        f"{_next_week_weekday_table(week_end)}\n"
    )

    # Section A — Meritco
    parts.append("\n" + "=" * 70 + "\n## A. 久谦专家纪要（本周，按日期）\n" + "=" * 70)
    for i, m in enumerate(meritco, 1):
        fm = m["frontmatter"]
        parts.append(
            f"\n--- 纪要 {i}/{len(meritco)} ---\n"
            f"meritco_id: {fm.get('id', '')}\n"
            f"source_url: {m['source_url'] or '(unknown)'}\n"
            f"date: {m['date']}\n"
            f"industry: {fm.get('industry', '')}\n"
            f"tickers: {fm.get('tickers', [])}\n"
            f"expert: {fm.get('sender_name', '')}\n"
            f"title: {fm.get('subject', '')}\n\n"
            f"{m['body']}\n"
        )

    # Section B — Weekly emails
    parts.append("\n" + "=" * 70 + "\n## B. 卖方周报邮件（本周）\n" + "=" * 70)
    for i, e in enumerate(weekly_emails, 1):
        fm = e["frontmatter"]
        parts.append(
            f"\n--- 邮件 {i}/{len(weekly_emails)} ---\n"
            f"date: {e['date']}\n"
            f"from: {fm.get('sender_name', '')} <{fm.get('sender_address', '')}>\n"
            f"subject: {fm.get('subject', '')}\n\n"
            f"{e['body']}\n"
        )

    # Section C — Daily digests (read-only context for cross-check)
    parts.append("\n" + "=" * 70 + "\n## C. 本周 daily digest（参照基准，仅用于印证/证伪判断）\n" + "=" * 70)
    for d in daily_digests:
        parts.append(f"\n--- daily {d['date']} ---\n{d['body']}\n")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def summarize_weekly(
    mail_dir: Path,
    meritco_dir: Path,
    daily_digest_dir: Path,
    weekly_senders: set[str],
    output_dir: Path,
    week_end: date | None = None,
    model: str = "claude-opus-4-7",
    max_tokens: int = 32000,
) -> Path:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if week_end is None:
        # Default to the most recent Sunday (today if Sunday, else previous Sunday)
        today = date.today()
        days_since_sun = (today.weekday() + 1) % 7  # Mon=0 → 1, Sun=6 → 0
        week_end = today - timedelta(days=days_since_sun)

    week_dates = _week_dates(week_end)
    week_start = week_dates[0]
    logger.info(f"Weekly digest: {week_start.isoformat()} → {week_end.isoformat()}")

    weekly_senders_lower = {s.lower() for s in weekly_senders}

    meritco = _load_meritco_week(meritco_dir, week_dates)
    weekly_emails = _load_weekly_emails(mail_dir, week_dates, weekly_senders_lower)
    daily_digests = _load_daily_digests(daily_digest_dir, week_dates)

    logger.info(
        f"Loaded {len(meritco)} meritco / {len(weekly_emails)} weekly emails / "
        f"{len(daily_digests)} daily digests"
    )

    if not meritco and not weekly_emails:
        raise RuntimeError("No weekly inputs found (meritco + weekly emails both empty).")

    user_text = _build_user_text(meritco, weekly_emails, daily_digests, week_start, week_end)

    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    logger.info(f"Calling Claude API ({model}) [streaming]...")

    chunks: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=WEEKLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            chunks.append(text)
        print()
        final = stream.get_final_message()

    digest = "".join(chunks)
    logger.info(
        f"API: {final.usage.input_tokens} in / {final.usage.output_tokens} out, "
        f"stop_reason={final.stop_reason}"
    )
    if final.stop_reason == "max_tokens":
        digest += (
            "\n\n---\n\n> ⚠️ 输出被 max_tokens 截断，请增大 max_tokens 重跑。\n"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{week_end.isoformat()}_weekly_digest.md"
    out_path.write_text(digest, encoding="utf-8")
    logger.info(f"Weekly digest written to {out_path}")

    _print_weekly_sources(weekly_emails, meritco, daily_digests)
    return out_path


def _print_weekly_sources(
    weekly_emails: list[dict], meritco: list[dict], daily_digests: list[dict]
) -> None:
    """Print the weekly inputs that fed this digest."""
    print(f"\n{'='*70}")
    print(
        f"📥 本次引用：{len(weekly_emails)} 封周报邮件 + "
        f"{len(meritco)} 条久谦纪要 + {len(daily_digests)} 份每日摘要"
    )
    print('='*70)
    if weekly_emails:
        print(f"\n📧 周报邮件 ({len(weekly_emails)})：")
        for i, email in enumerate(weekly_emails, 1):
            fm = email["frontmatter"]
            sender = fm.get("sender_name", "?")
            subject = fm.get("subject", "?")
            print(f"  {i:2d}. [{email.get('date','')}] {sender} — {subject}")
    if meritco:
        print(f"\n📝 久谦纪要 ({len(meritco)})：")
        for i, m in enumerate(meritco, 1):
            fm = m["frontmatter"]
            title = fm.get("subject", "?")
            tickers = fm.get("tickers", []) or []
            tickers_str = ",".join(tickers) if tickers else "—"
            print(f"  {i:2d}. [{m.get('date','')}] {tickers_str} — {title}")
    if daily_digests:
        print(f"\n📰 每日摘要 ({len(daily_digests)})：")
        for d in daily_digests:
            print(f"  - {d.get('date','')}")
    print('='*70)
