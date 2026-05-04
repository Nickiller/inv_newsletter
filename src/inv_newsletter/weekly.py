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

WEEKLY_SYSTEM_PROMPT = """\
你是一位资深 TMT 投研分析师助手。请基于本周的久谦专家纪要、卖方周报和本周已生成的 daily digest，
整理一份**周度投研总结**。

## 全局硬性规则

1. **禁止偷懒表达**：不允许使用"详情参见原文 / 具体见链接 / 细节需查阅 / 见附件"等推卸说法。
   每个 ticker / 主题段落必须给出 ≥3 个具体数据点；若素材不足以提取 3 个数据点，**完全省略该段**，
   不要保留只有"细节请看链接"的空架子。
2. **URL 必须保留**：原文中所有外链（WSJ / Bloomberg / Tae Kim / Substack / x.com / 久谦 source_url 等）
   都必须以 `[来源名](URL)` 内联格式紧跟在相关内容后；同一条多个链接并排列出。**严禁**把链接单独
   起一个 bullet 列出。仅当原文确实无 URL 时才允许纯文本来源标注。
   - ✅ 正确：`Anthropic ARR 突破 $44B [SemiAnalysis](https://...) [TMTB](https://...)`
   - ❌ 错误：` - Anthropic ARR 突破 $44B\n - [SemiAnalysis](https://...) [TMTB](https://...)`
3. **下周日历日期 / 星期几**：用户消息顶部给出"下周日期 → weekday"对照表，**必须严格照抄**，
   不得自行推算（容易写错）。
4. **金融术语保留英文**：buy-side / consensus / guidance / beat / miss / read through 等；
   特别提醒：`read through` **不要**翻译成"读穿"，保留英文。

## 输入构成
- **A. 久谦专家纪要（本周）**：每条都附带 `meritco_id` 和 `source_url`，请保留链接
- **B. 卖方周报邮件（本周）**：含 Bernstein Weekly Tech Check / Zukin's Next Week /
  Wolfe Software Sunday / Wolfe Internet Week Ahead / Jefferies Sunday Scoreboard /
  Stratechery / Funda AI Weekly 等
- **C. 本周已生成的 daily digest**：作为参照基准，用于判断本周内信号的"印证/证伪/新增"

## 输出要求（6 段，按重要性排序）

### Section 1. 财报季：下周关键 Earnings 的 Bogey & Setup（最重要）
- **从输入材料里识别下周（week+1）所有重要 earnings 事件**（mega-cap 优先：MSFT/GOOGL/META/AMZN/AAPL/NVDA/SPOT/BKNG/RDDT/RBLX/ROKU/ADBE/NOW/DDOG/CRM 等）
- 每个 ticker 一个小段，结构：
  ```
  #### TICKER (公司名) — 财报时间
  **Bogey（一致预期 / buy-side 高点）**
  - Revenue / EPS consensus
  - 关键业务线指标：Azure cc / AWS cc / Ad rev / cRPO / NEW ARR / DAU / MAU 等
  - Buy-side whisper（如有）

  **Setup（仓位 / 情绪 / 进场角度）**
  - Sentiment（long-and-strong / crowded long / underowned / contrarian short）
  - 近 N 周股价表现 / overbought 程度
  - 卖方推荐倾向（OP / MP / Buy / Sell）

  **关键 Debate / Drivers**
  - 财报最关键 1-3 个 debate（如 "Capex 是否再上调"、"Azure 是否加速"、"Reels CPM trend"）
  - **本周新增数据点**（来自 daily / 久谦 / 卖方周报）—— 这就是隐含的 daily 印证/证伪：
    - 例：`久谦 4/23 Nebius 专家：H100 +40%、GB200 Q2 再 +20% (04/23)` 印证了 daily 4/22 的 GPU 涨价信号
    - 例：`Wolfe Zukin 04/24 long-and-strong MSFT，better Azure + Copilot trends`

  **来源**：daily ({MM/DD}, {MM/DD}) · 久谦 [MM/DD 专家简称](source_url) · [MM/DD 专家简称](source_url) · {卖方周报名 (MM/DD)}
  ```
  - **久谦的部分必须用 markdown 链接形式 `[MM/DD 专家简称](source_url)`**，URL 来自输入材料的 `source_url` 字段，多条用 ` · ` 分隔
  - daily 和卖方部分保持纯文本（无链接）即可
- **无 earnings 但有重大 catalyst 的 ticker**（如 NOW Financial Analyst Day 5/4）也可以列入，标 "🎤 Investor Day"
- 数据点必须保留具体数字（$ / % / bps），术语保留英文（cRPO, beat/miss, guidance 等）
- **轻量化规则**：如果某 ticker 可用素材 < 3 个独立数据点，简化为紧凑 bullet list（不分 Bogey/Setup/Drivers 三级标题），
  避免空架子；甚至可只用一行总结。

### Section 2. 本周已报 Earnings 回看（thesis 印证 / 证伪 / 翻车）
- 列出本周已经发布财报的标的（重点是 Mega Cap：MSFT / GOOGL / META / AMZN / AAPL / NVDA / NFLX / SPOT 等）
- 每个 ticker 一条紧凑 bullet，结构：
  ```
  **TICKER**：财报关键数 vs 预期 → 印证/证伪了哪条 thesis → T+1 反应 → 后续含义
  ```
- 例：
  ```
  **GOOGL**：GCP +63% (vs 买方 +50%)，Cloud backlog $462B (~翻倍) → 印证了 04/27 久谦专家 "GCP 加速 +10pp/季" 的判断 →
  T+1 +6%，PT 上调至 $460 → 2027 Capex 买方共识抬至 $275B
  ```
- 无 thesis 印证/证伪含义的常规 in-line 报告可一行带过；爆雷 / 大超预期重点展开
- 数据来源以本周的 daily digest + 卖方 EPS recap 邮件为主

### Section 3. 本周板块表现 & 关键价格信号
- 紧凑列出本周值得关注的板块/个股价格信号，3-6 条即可，每条要点：
  - 板块涨跌（Semis / Software / Internet / Crypto / Defense 等）+ 关键驱动
  - T+1 财报反应里的极端走势（远超/远逊 positioning 隐含）
  - Overbought / Oversold 信号（RSI / 涨跌天数 / sentiment matrix 极值）
  - 主要 sector winners/losers Top 5（如 Jefferies HF/CTA 资金流数据）
- 数据从 Bernstein Weekly Tech Check、Jefferies Scoreboard、JPM Sentiment Matrix 等周报里抽取
- **目的**：让读者一眼看到本周 risk-on/off 的方向和强度，不重复 Section 4 卖方观点

### Section 4. 卖方周报观点综合
- 按发件源（Bernstein Weekly Tech Check / Wolfe Zukin / Wolfe Internet / Jefferies Scoreboard / Stratechery / Funda AI）分小段
- 每段 3-6 条最关键观点，引用具体数据
- 保留邮件原文里的所有外链 `[来源名](URL)` —— 见全局规则 #2，违反将被视为输出错误

### Section 5. 久谦专家本周观察（按 Ticker 归类）
- 用 `### TICKER (公司名)` 作为小标题；同一 ticker 多次出现要合并
- **来源链接放在 ticker 标题正下方一行内集中列出**，格式：
  `**久谦来源**：[MM/DD 专家简称](source_url) · [MM/DD 专家简称](source_url)`
  **不要**用 `*...*` 斜体包裹整行（飞书渲染会吞掉斜体内的链接）。
  专家简称从 `expert` 字段提取关键 4-8 字（如 "MRVL 离职专家"、"Cognizant 离职专家"、"Nebius 专家"）
- 同一 ticker 引用同一篇纪要多次时，链接只在顶部出现一次，不要在 bullets 内重复
- 正文 bullets **不再附链接**，只在末尾用 `(MM/DD)` 标日期，跨多篇时写 `(04/20·04/21)`
- 提取关键数据点（具体数字、百分比、市场份额、产能、价格等），不需要保留 Q&A 原文
- 跳过医疗/医药/健康行业

示例格式：
```
### MRVL (Marvell Technology)
**久谦来源**：[04/20 通信硬件专家](url) · [04/21 MRVL 离职专家](url)

- Google ASIC 合作确认：... 三年意向订单 $150-200 亿。(04/20)
- 收入展望：2026 年 $20-30 亿，2027 年 $60-70 亿... (04/21)
- CXL 池化推进超预期：... (04/20·04/21)
```

### Section 6. 下周关注（Catalysts Calendar）
- 紧凑表格：日期 · weekday · 事件（weekday 必须照抄用户消息顶部给的对照表）
- 财报、investor day、行业会议、数据发布、政府/监管事件

## 输出格式
```markdown
# Weekly Research Digest — Week ending {Sunday YYYY-MM-DD}
> 周一 {Mon} → 周日 {Sun}，基于 N 条久谦纪要 + M 封卖方周报 + K 篇 daily digest 整理。

---

## 1. 财报季：下周关键 Earnings 的 Bogey & Setup
#### TICKER (公司名) — 财报时间
**Bogey** / **Setup** / **关键 Debate / Drivers**
**来源**：daily (...) · 久谦 (...) · 卖方 (...)

---

## 2. 本周已报 Earnings 回看
- **TICKER**：实际数 vs 预期 → 印证/证伪 thesis → T+1 反应 → 含义

---

## 3. 本周板块表现 & 关键价格信号
- 板块/资金流/极端走势/超买超卖 — 3-6 条紧凑 bullet

---

## 4. 卖方周报观点综合
### Bernstein Weekly Tech Check ({date})
- ...（保留所有 URL）

---

## 5. 久谦专家本周观察（按 Ticker）
### NVDA (英伟达)
**久谦来源**：[MM/DD 专家简称](source_url)
- ...

---

## 6. 下周关注（Catalysts Calendar）
| 日期 | weekday | 事件 |
|---|---|---|
| ... | ... | ... |
```
"""


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
