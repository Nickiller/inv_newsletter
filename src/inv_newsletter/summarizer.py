"""Claude API-based email summarization with multimodal image support."""

import base64
import json
import logging
import os
import re
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import yaml

from .taxonomy import Taxonomy, get_default_taxonomy
from .timing import get_timer
from .tldr import TLDR_DEFAULT_MODEL, generate_tldr, prepend_tldr

logger = logging.getLogger(__name__)

last_usage: dict = {}  # populated by summarize_daily with {input_tokens, output_tokens, stop_reason}

# Section / industry order and ticker classification are sourced from
# src/inv_newsletter/data/taxonomy.yaml (loaded once via get_default_taxonomy).
# CANONICAL_SECTIONS is kept as a module attribute for backwards compatibility
# with callers that imported it; both the prompt (via {{TAXONOMY_BLOCK}}) and
# post-process (_reorder_sections) read directly from the taxonomy now.
CANONICAL_SECTIONS = get_default_taxonomy().sector_order()

# Per-million-token USD prices (Anthropic public pricing). Update if pricing changes.
_PRICE_PER_MTOK = {
    "opus":   (15.00, 75.00),
    "sonnet": (3.00, 15.00),
    "haiku":  (1.00,  5.00),
}
_run_usage: list[dict] = []  # accumulated per summarize_daily run; reset at function entry


def _price_tier(model: str) -> str | None:
    m = model.lower()
    for tier in _PRICE_PER_MTOK:
        if tier in m:
            return tier
    return None


def _record_usage(model: str, usage) -> None:
    _run_usage.append({
        "model": model,
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    })


def _estimate_tokens_from_text(text: str) -> int:
    # Fallback for proxies that don't relay the streaming message_delta event,
    # leaving final.usage.output_tokens=0. ~4 ASCII chars/token, ~1 token/CJK char.
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return int(ascii_n / 4 + (len(text) - ascii_n))


def _format_cost_report() -> str:
    if not _run_usage:
        return ""
    by_model: dict[str, dict] = {}
    for r in _run_usage:
        e = by_model.setdefault(r["model"], {"calls": 0, "in": 0, "out": 0, "cwrite": 0, "cread": 0})
        e["calls"] += 1
        e["in"] += r["input_tokens"]
        e["out"] += r["output_tokens"]
        e["cwrite"] += r["cache_creation_input_tokens"]
        e["cread"] += r["cache_read_input_tokens"]
    lines = ["", "=" * 70, "💰 本次运行 token 用量与估算费用", "=" * 70]
    total = 0.0
    unknown: list[str] = []
    for model, e in by_model.items():
        tier = _price_tier(model)
        if tier is None:
            unknown.append(model)
            cost_str = "N/A"
            cache_str = ""
        else:
            in_p, out_p = _PRICE_PER_MTOK[tier]
            # Anthropic cache pricing: write = 1.25x input, read = 0.1x input
            cost = (
                e["in"] / 1_000_000 * in_p
                + e["out"] / 1_000_000 * out_p
                + e["cwrite"] / 1_000_000 * in_p * 1.25
                + e["cread"] / 1_000_000 * in_p * 0.1
            )
            total += cost
            cost_str = f"${cost:.4f}"
            cache_str = f", cache w/r {e['cwrite']:,}/{e['cread']:,}" if (e["cwrite"] or e["cread"]) else ""
        lines.append(
            f"  {model}: {e['calls']} 调用, "
            f"in {e['in']:,} / out {e['out']:,} tokens{cache_str} → {cost_str}"
        )
    lines.append("-" * 70)
    suffix = f"  (未识别模型: {', '.join(unknown)})" if unknown else ""
    lines.append(f"  总计: ${total:.4f}{suffix}")
    lines.append("=" * 70)
    return "\n".join(lines)

MIN_IMAGE_SIZE = 35 * 1024  # 35KB — skip logos/banners but keep small data charts
MAX_IMAGES_PER_EMAIL = 5  # 每封邮件最多 5 张图（图表多的邮件如 JPM Sentiment Monitor 需要更多额度）
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MERITCO_URL_TEMPLATE = "https://research.meritco-group.com/forum?forumType=2&forumId={id}"
MERITCO_EXCLUDED_INDUSTRIES = (
    "医疗", "医药", "健康", "创新药", "生物科技", "生物医药", "制药", "生命科学"
)

# Haiku-based image caption pre-pass (binds IMG_XX ↔ chart content for the main LLM)
CAPTION_MODEL = "claude-haiku-4-5-20251001"
CAPTION_CACHE_FILE = Path("data/.image_caption_cache.json")
_PROMPTS_DIR = Path(__file__).parent / "prompts"
CAPTION_PROMPT = (_PROMPTS_DIR / "image_caption.md").read_text(encoding="utf-8").strip()

_TAXONOMY_PLACEHOLDER = "{{TAXONOMY_BLOCK}}"


def _inject_taxonomy(prompt: str, taxonomy: Taxonomy | None = None) -> str:
    """Substitute {{TAXONOMY_BLOCK}} with the rendered taxonomy table.

    Falls back to a clear error if the placeholder is missing — silent
    fall-through would leave the LLM without any sector/industry guidance.
    """
    if _TAXONOMY_PLACEHOLDER not in prompt:
        raise RuntimeError(
            f"prompt missing {_TAXONOMY_PLACEHOLDER} placeholder; "
            f"taxonomy injection requires the placeholder to be present in the prompt file."
        )
    tax = taxonomy or get_default_taxonomy()
    return prompt.replace(_TAXONOMY_PLACEHOLDER, tax.render_prompt_block().rstrip())


SYSTEM_PROMPT = _inject_taxonomy(
    (_PROMPTS_DIR / "digest_system_v3.md").read_text(encoding="utf-8")
)


def summarize_daily(
    data_dir: Path,
    output_dir: Path,
    target_date: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 16000,
    meritco_dir: Path | None = None,
    meritco_days: int = 3,
    filename_suffix: str = "",
    prompt_file: Path | None = None,
    tldr_model: str = TLDR_DEFAULT_MODEL,
) -> Path:
    """Load emails for a date, call Claude API, write digest. Returns output path.

    prompt_file: optional override for the system prompt. Defaults to
    prompts/digest_system_v3.md (loaded as SYSTEM_PROMPT at module import).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to .env or environment.")

    system_prompt = SYSTEM_PROMPT
    if prompt_file is not None:
        raw = Path(prompt_file).read_text(encoding="utf-8")
        system_prompt = _inject_taxonomy(raw) if _TAXONOMY_PLACEHOLDER in raw else raw
        logger.info(f"Using custom system prompt: {prompt_file}")

    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    # Determine date
    if target_date is None:
        # Find the most recent date directory
        date_dirs = sorted(data_dir.glob("20*-*-*"), reverse=True)
        if not date_dirs:
            raise RuntimeError(f"No email data found in {data_dir}")
        target_date = date_dirs[0].name
    else:
        if not (data_dir / target_date).exists():
            raise RuntimeError(f"No data for date {target_date} in {data_dir}")

    timer = get_timer()

    with timer.phase("load_inputs", "cpu"):
        date_dir = data_dir / target_date
        emails = _load_emails(date_dir)

        # Load Meritco minutes from past N days (today + N-1 prior)
        meritco_entries: list[dict] = []
        if meritco_dir is not None and meritco_days > 0:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
            for offset in range(meritco_days):
                d = target_dt - timedelta(days=offset)
                day_dir = meritco_dir / d.isoformat()
                if day_dir.exists():
                    meritco_entries.extend(_load_meritco(day_dir, d.isoformat()))
            logger.info(
                f"Loaded {len(meritco_entries)} Meritco minutes from past {meritco_days} day(s)"
            )

    if not emails and not meritco_entries:
        raise RuntimeError(f"No emails or meritco minutes found for {target_date}")

    logger.info(
        f"Summarizing {len(emails)} emails + {len(meritco_entries)} meritco minutes for {target_date}"
    )

    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    _run_usage.clear()

    # Pre-pass: caption every chart image with Haiku so the main LLM has a
    # text binding between IMG_XX and chart content (avoids visual/text mismatches).
    captions = _caption_all_images(client, emails)

    # Build API request — also collect img_id → path mapping
    with timer.phase("build_blocks", "cpu"):
        content_blocks, img_map, img_caption = _build_content_blocks(emails, meritco_entries, captions)

    logger.info(f"Calling Claude API ({model}) [streaming]...")
    chunks = []
    t_main_start = time.perf_counter()
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content_blocks}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            chunks.append(text)
        print()  # newline after streaming
        final = stream.get_final_message()
    main_duration = time.perf_counter() - t_main_start

    digest = "".join(chunks)
    tokens_in = final.usage.input_tokens
    tokens_out = final.usage.output_tokens
    cache_write = getattr(final.usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(final.usage, "cache_read_input_tokens", 0) or 0
    stop_reason = final.stop_reason

    # Some proxies drop the final message_delta SSE event, leaving output_tokens=0
    # and stop_reason=None even though the text streamed back fine. Fall back to a
    # length-based estimate so cost/telemetry stays useful.
    tokens_out_estimated = False
    if tokens_out == 0 and digest:
        tokens_out = _estimate_tokens_from_text(digest)
        tokens_out_estimated = True
        logger.warning(
            f"Streaming response missing usage (likely proxy quirk). "
            f"Estimated output_tokens from text length: ~{tokens_out}"
        )
    if stop_reason is None and digest:
        stop_reason = "end_turn"  # inferred; proxy didn't relay message_delta

    cache_msg = ""
    if cache_write:
        cache_msg = f", cache write +{cache_write}"
    elif cache_read:
        cache_msg = f", cache hit {cache_read}"
    out_label = f"~{tokens_out} (est)" if tokens_out_estimated else str(tokens_out)
    logger.info(f"API response: {tokens_in} input tokens{cache_msg}, {out_label} output tokens, stop_reason: {stop_reason}")
    last_usage.clear()
    last_usage.update({
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "stop_reason": stop_reason,
        "output_tokens_estimated": tokens_out_estimated,
    })
    _run_usage.append({
        "model": model,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
    })
    timer.record_llm_call(
        "main_digest",
        model=model,
        duration_sec=main_duration,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        stop_reason=stop_reason,
        tokens_out_estimated=tokens_out_estimated,
    )

    # Detect truncation
    if stop_reason == "max_tokens":
        logger.warning(
            f"⚠️ Output truncated! stop_reason=max_tokens (limit={max_tokens}). "
            f"Increase max_tokens in filters.yaml or pass a higher value."
        )
        digest += (
            "\n\n---\n\n"
            "> ⚠️ **注意：本摘要因 max_tokens 限制被截断，内容不完整。**\n"
            f"> stop_reason: max_tokens, output_tokens: {tokens_out}, limit: {max_tokens}\n"
        )

    # Write output — markdown in output_dir, images in output_dir/{date}/
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / target_date
    output_path = output_dir / f"{target_date}_daily_digest{filename_suffix}.md"

    with timer.phase("write_output", "cpu"):
        # Deterministic post-processing: drop reused/mismatched/out-of-range image refs
        digest = _validate_image_refs(digest, img_caption)

        # Copy referenced images to date subdir and replace IMG_XX with relative paths
        digest = _embed_images(digest, img_map, img_dir, target_date)

        # Enforce canonical top-level section order + industry-level ordering (LLM drifts despite prompt)
        digest = _reorder_sections(digest)

        # Drift audit: detect ticker headings in the wrong sector + tickers not in taxonomy
        report = _drift_audit(digest)
        _write_drift_logs(report, target_date, Path("logs"))
        digest = _append_audit_footer(digest, report, target_date)
        if report["misclassified"] or report["unmapped"]:
            logger.info(
                f"Audit: misclassified={len(report['misclassified'])}, "
                f"unmapped={len(report['unmapped'])} — see logs/"
            )

    # Stage-2 TL;DR: extract `## 今日要点` from the rendered draft (separate LLM call).
    # Cheaper than asking stage-1 to synthesize across 90k of raw email noise, and
    # produces a TL;DR grounded in the actually-shipped digest body.
    logger.info(f"Generating stage-2 TL;DR ({tldr_model})...")
    t_tldr_start = time.perf_counter()
    try:
        tldr_text, tldr_usage = generate_tldr(digest, model=tldr_model, client=client)
        tldr_duration = time.perf_counter() - t_tldr_start
        logger.info(
            f"Stage-2 TL;DR: {tldr_usage['input_tokens']} in / {tldr_usage['output_tokens']} out "
            f"tokens, {tldr_duration:.1f}s, stop_reason: {tldr_usage['stop_reason']}"
        )
        _run_usage.append({
            "model": tldr_model,
            "input_tokens": tldr_usage["input_tokens"],
            "output_tokens": tldr_usage["output_tokens"],
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        })
        timer.record_llm_call(
            "stage2_tldr",
            model=tldr_model,
            duration_sec=tldr_duration,
            tokens_in=tldr_usage["input_tokens"],
            tokens_out=tldr_usage["output_tokens"],
            stop_reason=tldr_usage["stop_reason"],
        )
        digest = prepend_tldr(digest, tldr_text)
    except Exception as e:
        logger.warning(f"Stage-2 TL;DR failed, publishing without TL;DR: {e}")

    with timer.phase("write_output", "cpu"):
        output_path.write_text(digest, encoding="utf-8")
    logger.info(f"Digest written to {output_path}")

    _print_sources(emails, meritco_entries)
    report = _format_cost_report()
    if report:
        print(report)
    return output_path


def _norm_section_title(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s).lower()


def _reorder_industries_within_section(
    section_body: str, sector_name: str, taxonomy: Taxonomy
) -> str:
    """Reorder ### industry headings within a ## sector per taxonomy.industry_order.

    Unknown industries (LLM-coined titles not in taxonomy) keep their relative
    order and are appended after the known ones.
    """
    industry_order = taxonomy.industry_order(sector_name)
    if not industry_order:
        return section_body

    lines = section_body.split("\n")
    h3_starts = [i for i, l in enumerate(lines) if l.startswith("### ")]
    if len(h3_starts) < 2:
        return section_body

    preamble = "\n".join(lines[: h3_starts[0]]).rstrip()

    chunks: list[tuple[str, str]] = []
    for idx, start in enumerate(h3_starts):
        end = h3_starts[idx + 1] if idx + 1 < len(h3_starts) else len(lines)
        title = lines[start][4:].strip()
        body = "\n".join(lines[start:end]).rstrip()
        chunks.append((title, body))

    canon_norm = [_norm_section_title(t) for t in industry_order]

    def rank(title: str) -> tuple[int, int]:
        norm = _norm_section_title(title)
        if norm in canon_norm:
            return (canon_norm.index(norm), 0)
        return (len(canon_norm), 0)  # unknown industries appended after known

    # stable sort preserves order among unknowns
    chunks.sort(key=lambda x: rank(x[0]))

    parts = [preamble] + [c[1] for c in chunks]
    return "\n\n".join(p for p in parts if p)


def _reorder_sections(digest: str, taxonomy: Taxonomy | None = None) -> str:
    """Reorder top-level ## sections + ### industries per taxonomy.

    Sections not in the canonical list are inserted between '软件与SaaS' and '其他'
    (preserves their relative order). Within each section, ### industry subheadings
    are reordered per taxonomy.industry_order(sector). Preamble (H1 + any
    pre-section text) is kept on top.
    """
    tax = taxonomy or get_default_taxonomy()
    sector_order = tax.sector_order()

    lines = digest.split("\n")
    section_starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if len(section_starts) < 2:
        return digest

    preamble = "\n".join(lines[: section_starts[0]]).rstrip()

    sections: list[tuple[str, str, str]] = []  # (raw_title, canonical_sector_or_None, body)
    for idx, start in enumerate(section_starts):
        end = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(lines)
        title = lines[start][3:].strip()
        body = "\n".join(lines[start:end]).rstrip()
        canonical = _match_canonical_sector(title, sector_order)
        if canonical:
            body = _reorder_industries_within_section(body, canonical, tax)
        sections.append((title, canonical, body))

    canon_norm = [_norm_section_title(t) for t in sector_order]
    unknown_anchor = canon_norm.index(_norm_section_title("其他")) if "其他" in sector_order else len(canon_norm)

    def rank(canonical: str | None, raw_title: str) -> tuple[int, int]:
        if canonical:
            return (canon_norm.index(_norm_section_title(canonical)), 0)
        return (unknown_anchor, -1)  # before "其他", after the previous known sector

    sections.sort(key=lambda x: rank(x[1], x[0]))

    parts = [preamble] + [s[2] for s in sections]
    return "\n\n".join(p for p in parts if p) + "\n"


def _match_canonical_sector(title: str, sector_order: list[str]) -> str | None:
    norm_title = _norm_section_title(title)
    for canonical in sector_order:
        if _norm_section_title(canonical) == norm_title:
            return canonical
    return None


# ── Drift audit ──────────────────────────────────────────────────────────


# Match the leading chunk of a #### / ### heading before " — " / " - " / " (" / EOL.
# Used to lift "NVDA" out of "NVDA (NVIDIA) — body" and "SK Hynix" out of "SK Hynix — body".
# Applied to both H4 (ticker headings) and H3 fallback (when LLM skipped H4 level).
_TICKER_HEADING_RE = re.compile(r"^#{3,4}\s+(.+?)(?:\s+[—–\-:]|\s+\(|$)", re.MULTILINE)

# A bare ticker-shaped token: 1-6 ASCII uppercase letters/digits. Used to detect
# headings worth flagging as 'unmapped' when they have no taxonomy match. Theme
# headings ("CPO 节奏前移", "Apple-Intel 协议") fail this and are skipped silently.
_TICKER_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")

# First leading ASCII uppercase token (e.g. "TSMC" out of "TSMC 与 COUPE 路线图").
_LEADING_ASCII_TICKER_RE = re.compile(r"^([A-Z][A-Za-z0-9]{0,7})\b")


def _classify_heading_candidate(
    heading_text: str, taxonomy: Taxonomy
) -> tuple[tuple[str, str, str] | None, str, bool]:
    """Try to classify the leading 'subject' of a #### heading.

    Returns (classification, candidate_text, is_ticker_shaped):
      - classification: (sector, industry, canonical_ticker) or None
      - candidate_text: best-guess subject pulled out of the heading
      - is_ticker_shaped: True if the candidate looks like a bare ticker token
        (worth flagging as 'unmapped' when taxonomy lookup fails)

    Theme headings ("CPO 节奏前移", "TSMC 与 COUPE / 先进封装路线图") that don't
    resolve to a ticker are returned with classification=None,
    is_ticker_shaped=False so the caller can skip them silently.
    """
    candidate = heading_text.strip()
    if not candidate:
        return None, "", False

    # 1. Try a full-string classify (handles "SK Hynix", "兆易创新", "Palo Alto Networks")
    result = taxonomy.classify(candidate)
    if result is not None:
        return result, candidate, True

    # 2. Try the first ASCII ticker token (handles "TSMC 与 COUPE 路线图" → TSMC)
    m = _LEADING_ASCII_TICKER_RE.match(candidate)
    if m:
        first_token = m.group(1)
        result = taxonomy.classify(first_token)
        if result is not None:
            return result, first_token, True

    # 3. No taxonomy hit. Only flag as 'unmapped' if the whole candidate
    #    looks like a bare ticker shape (uppercase, ≤6 chars, no spaces).
    is_ticker_shape = bool(_TICKER_SHAPE_RE.fullmatch(candidate))
    return None, candidate, is_ticker_shape


def _check_ticker_heading(
    line: str,
    current_sector: str,
    taxonomy: Taxonomy,
    misclassified: list[dict],
    unmapped: list[dict],
) -> None:
    """Run ticker drift checks against a #### / ### heading line.

    Appends to misclassified / unmapped in place. Theme headings without a
    ticker subject are skipped silently.
    """
    m = _TICKER_HEADING_RE.match(line)
    if not m:
        return
    result, candidate, is_ticker_shape = _classify_heading_candidate(m.group(1), taxonomy)
    if result is None:
        if is_ticker_shape:
            unmapped.append({
                "kind": "ticker",
                "ticker": candidate,
                "found_in": current_sector,
                "heading": line.strip(),
            })
        return
    accepted_sectors = {loc[0] for loc in taxonomy.accepted_locations(candidate)}
    if current_sector not in accepted_sectors:
        misclassified.append({
            "kind": "ticker",
            "ticker": candidate,
            "canonical_ticker": result[2],
            "found_in": current_sector,
            "expected": result[0],
            "heading": line.strip(),
        })


def _drift_audit(digest: str, taxonomy: Taxonomy | None = None) -> dict:
    """Detect misclassifications + unmapped tickers in #### and ### headings.

    Returns dict with:
      - misclassified: list of records; each record has ``kind`` ∈ {"ticker", "industry"}
        - ticker drift: {kind: "ticker", ticker, canonical_ticker, found_in, expected, heading}
        - industry drift: {kind: "industry", industry, found_in, expected, heading}
      - unmapped: list of {kind: "ticker", ticker, found_in, heading}

    Detection scope:
      - `#### TICKER` headings: classified as ticker drift if ticker is in
        taxonomy but not in any accepted (primary + also_in) sector.
      - `### industry` headings: if the heading text matches a known
        taxonomy industry, classified as industry drift when found in the
        wrong sector. Otherwise the H3 is treated as a possible ticker
        heading (catches cases where the LLM put `### CRCL` instead of
        `#### CRCL`).
      - Body-text cross-references (NVDA mentioned inside TSMC body) are
        NOT flagged.
      - Theme headings without a ticker / industry subject are skipped
        silently (e.g. `#### CPO 节奏前移`).
    """
    tax = taxonomy or get_default_taxonomy()
    misclassified: list[dict] = []
    unmapped: list[dict] = []

    lines = digest.split("\n")
    current_sector: str | None = None
    for line in lines:
        if line.startswith("## "):
            title = line[3:].strip()
            current_sector = _match_canonical_sector(title, tax.sector_order()) or title
            continue
        if current_sector is None:
            continue

        if line.startswith("#### "):
            _check_ticker_heading(line, current_sector, tax, misclassified, unmapped)
            continue

        if line.startswith("### "):
            heading_text = line[4:].strip()
            # First try as an industry name (allows minor punctuation differences).
            owner = tax.industry_to_sector(heading_text)
            if owner is not None:
                if owner != current_sector:
                    misclassified.append({
                        "kind": "industry",
                        "industry": heading_text,
                        "found_in": current_sector,
                        "expected": owner,
                        "heading": line.strip(),
                    })
                continue
            # Not a known industry → maybe LLM used ### where it should have
            # used #### for a single ticker (e.g. "### CRCL — ..."). Fall
            # through to ticker check.
            _check_ticker_heading(line, current_sector, tax, misclassified, unmapped)

    return {"misclassified": misclassified, "unmapped": unmapped}


def _drift_subject(item: dict) -> str:
    """Return the human-facing subject of a drift record (ticker symbol or industry name)."""
    if item.get("kind") == "industry":
        return item.get("industry", "?")
    return item.get("canonical_ticker") or item.get("ticker") or "?"


def _write_drift_logs(report: dict, target_date: str, logs_dir: Path) -> None:
    """Write drift + unmapped findings to logs/ for human review.

    File format is append-only newline-delimited records for easy `tail -f` review.
    Each drift record is prefixed with its ``kind`` (ticker | industry).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    if report["misclassified"]:
        with (logs_dir / "digest_drift.log").open("a", encoding="utf-8") as fp:
            for item in report["misclassified"]:
                kind = item.get("kind", "ticker")
                subject = _drift_subject(item)
                fp.write(
                    f"{target_date}\t{kind}\t{subject}\t"
                    f"found_in={item['found_in']}\texpected={item['expected']}\t"
                    f"heading={item['heading']}\n"
                )
    if report["unmapped"]:
        with (logs_dir / "unmapped_tickers.log").open("a", encoding="utf-8") as fp:
            for item in report["unmapped"]:
                fp.write(
                    f"{target_date}\t{item['ticker']}\tfound_in={item['found_in']}\t"
                    f"heading={item['heading']}\n"
                )


def _append_audit_footer(digest: str, report: dict, target_date: str) -> str:
    """Append an HTML-comment audit footer to the digest.

    Invisible in Feishu / WeChat rendered output but visible in raw markdown
    review. Lists counts + first few offenders inline so the eye-check is fast.
    """
    n_mis = len(report["misclassified"])
    n_un = len(report["unmapped"])
    if n_mis == 0 and n_un == 0:
        return digest.rstrip() + "\n\n<!-- audit: clean (no drift, no unmapped tickers) -->\n"
    lines = [
        f"<!-- audit ({target_date}): misclassified={n_mis}, unmapped={n_un}"
    ]
    for item in report["misclassified"][:10]:
        kind = item.get("kind", "ticker")
        subject = _drift_subject(item)
        lines.append(
            f"  - drift ({kind}): {subject} in {item['found_in']} → expected {item['expected']} "
            f"({item['heading']})"
        )
    if n_mis > 10:
        lines.append(f"  - ... and {n_mis - 10} more (see logs/digest_drift.log)")
    for item in report["unmapped"][:10]:
        lines.append(f"  - unmapped: {item['ticker']} in {item['found_in']} ({item['heading']})")
    if n_un > 10:
        lines.append(f"  - ... and {n_un - 10} more (see logs/unmapped_tickers.log)")
    lines.append("-->")
    return digest.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def _print_sources(emails: list[dict], meritco_entries: list[dict]) -> None:
    """Print the emails + meritco minutes that fed this digest."""
    print(f"\n{'='*70}")
    print(f"📥 本次引用：{len(emails)} 封邮件 + {len(meritco_entries)} 条久谦纪要")
    print('='*70)
    if emails:
        print(f"\n📧 邮件 ({len(emails)})：")
        for i, email in enumerate(emails, 1):
            fm = email["frontmatter"]
            sender = fm.get("sender_name", "?")
            subject = fm.get("subject", "?")
            received = fm.get("received_at", "")
            time_str = received[:16].replace("T", " ") if received else ""
            print(f"  {i:2d}. [{time_str}] {sender} — {subject}")
    if meritco_entries:
        print(f"\n📝 久谦纪要 ({len(meritco_entries)})：")
        for i, m in enumerate(meritco_entries, 1):
            fm = m["frontmatter"]
            title = fm.get("subject", "?")
            tickers = fm.get("tickers", []) or []
            tickers_str = ",".join(tickers) if tickers else "—"
            print(f"  {i:2d}. [{m.get('date','')}] {tickers_str} — {title}")
    print('='*70)


def _tokenize_caption(text: str) -> set[str]:
    """Tokenize a caption into chars (CJK) + lowercase ASCII words for overlap scoring."""
    text = (text or "").lower()
    # ASCII words: keep them whole
    words = set(re.findall(r"[a-z0-9]+", text))
    # CJK chars: each char is a token (skip ASCII chars / punctuation already covered)
    chars = {c for c in text if "一" <= c <= "鿿"}
    return words | chars


def _caption_overlap(label: str, inv_caption: str) -> float:
    """Directional overlap: fraction of label's tokens that appear in inventory caption.

    Asymmetric on purpose — the LLM's user-facing label is usually short ("AI 安全威胁"),
    while the inventory caption is verbose ("截图，AI 安全威胁应对策略与平台厂商竞争..."），
    so symmetric Jaccard would unfairly penalize legitimate matches. We accept any
    label whose tokens are mostly contained in the inventory caption.
    """
    a, b = _tokenize_caption(label), _tokenize_caption(inv_caption)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


CAPTION_MATCH_THRESHOLD = 0.3  # min directional overlap (label-tokens-in-inventory)


def _validate_image_refs(digest: str, img_caption: dict[str, str]) -> str:
    """Drop reused / out-of-range / caption-mismatched IMG_XX references.

    Strategy:
      1. Find every `![label](IMG_NN)` reference (with optional trailing 📊 description line)
      2. Group by IMG_NN
      3. For each group: pick the occurrence whose label has highest overlap with
         img_caption[IMG_NN]; drop all others. If even the best is below threshold,
         drop all occurrences.
      4. Out-of-range IDs (not in img_caption): drop all occurrences.

    Removed lines are replaced with empty strings (the surrounding text stands).
    """
    pattern = re.compile(r"!\[([^\]]*)\]\((IMG_\d+)\)[ \t]*\n?(?:📊[^\n]*\n?)?")

    # Collect all matches with positions
    matches = list(pattern.finditer(digest))
    if not matches:
        return digest

    # Group by IMG_NN
    by_id: dict[str, list[tuple[re.Match, float]]] = {}
    for m in matches:
        img_id = m.group(2)
        label = m.group(1)
        score = _caption_overlap(label, img_caption.get(img_id, ""))
        by_id.setdefault(img_id, []).append((m, score))

    # Decide which match position to keep (set of (start, end))
    keep_spans: set[tuple[int, int]] = set()
    drop_reasons: list[str] = []
    for img_id, items in by_id.items():
        if img_id not in img_caption:
            drop_reasons.append(f"  - {img_id}: out-of-range (not in inventory), dropping {len(items)} ref(s)")
            continue
        items.sort(key=lambda t: t[1], reverse=True)
        best_match, best_score = items[0]
        if best_score < CAPTION_MATCH_THRESHOLD:
            drop_reasons.append(
                f"  - {img_id}: best label overlap {best_score:.2f} < threshold "
                f"(inv: \"{img_caption[img_id]}\"), dropping all {len(items)} ref(s)"
            )
            continue
        keep_spans.add((best_match.start(), best_match.end()))
        if len(items) > 1:
            drop_reasons.append(
                f"  - {img_id}: kept best (overlap {best_score:.2f}), dropped {len(items)-1} duplicate(s)"
            )

    # Rebuild digest: drop matches not in keep_spans
    drop_count = 0
    out_parts: list[str] = []
    cursor = 0
    for m in matches:
        span = (m.start(), m.end())
        out_parts.append(digest[cursor:m.start()])
        if span in keep_spans:
            out_parts.append(m.group(0))
        else:
            drop_count += 1
        cursor = m.end()
    out_parts.append(digest[cursor:])

    if drop_count:
        logger.info(f"Image-ref validator dropped {drop_count} bad reference(s):")
        for line in drop_reasons:
            logger.info(line)
    return "".join(out_parts)


def _embed_images(digest: str, img_map: dict[str, Path], img_dir: Path, date_str: str) -> str:
    """Copy images referenced as IMG_XX into img_dir and rewrite markdown paths."""
    for img_id, src_path in img_map.items():
        if img_id not in digest:
            continue
        img_dir.mkdir(parents=True, exist_ok=True)
        ext = src_path.suffix.lower()
        dest_name = f"{img_id}{ext}"
        dest_path = img_dir / dest_name
        shutil.copy2(src_path, dest_path)
        # Use relative path from the .md file: {date}/IMG_XX.ext
        digest = digest.replace(img_id, f"{date_str}/{dest_name}")
        logger.debug(f"Copied image {img_id} → {date_str}/{dest_name}")
    return digest


def _load_emails(date_dir: Path) -> list[dict]:
    """Load all email.md files from a date directory."""
    emails = []
    for email_md in sorted(date_dir.glob("*/email.md")):
        email_dir = email_md.parent
        try:
            raw = email_md.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(raw)
            images = _select_key_images(email_dir, frontmatter.get("images", []))
            emails.append({
                "dir": email_dir,
                "frontmatter": frontmatter,
                "body": body,
                "images": images,
            })
        except Exception as e:
            logger.warning(f"Failed to load {email_md}: {e}")
    return emails


def _load_meritco(meritco_date_dir: Path, date_str: str) -> list[dict]:
    """Load meritco minutes from a date dir (filename pattern YYMMDD_*.md, no _meritco_ infix).

    Skips healthcare-related industries. Each entry includes source_url derived from
    frontmatter id (e.g. meritco-3114 → https://research.meritco-group.com/forum?...&forumId=3114).
    """
    entries = []
    for md_file in sorted(meritco_date_dir.glob("*.md")):
        try:
            raw = md_file.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(raw)
            industry = frontmatter.get("industry", "") or ""
            if any(kw in industry for kw in MERITCO_EXCLUDED_INDUSTRIES):
                continue
            source_url = _meritco_id_to_url(frontmatter.get("id", ""))
            entries.append({
                "dir": meritco_date_dir,
                "frontmatter": frontmatter,
                "body": body,
                "images": [],
                "source_url": source_url,
                "date": date_str,
            })
        except Exception as e:
            logger.warning(f"Failed to load {md_file}: {e}")
    return entries


def _meritco_id_to_url(meritco_id: str) -> str | None:
    """meritco-3114 → https://research.meritco-group.com/forum?forumType=2&forumId=3114"""
    m = re.search(r"(\d+)", str(meritco_id or ""))
    if not m:
        return None
    return MERITCO_URL_TEMPLATE.format(id=m.group(1))


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


def _load_caption_cache() -> dict[str, str]:
    if not CAPTION_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CAPTION_CACHE_FILE.read_text())
    except Exception as e:
        logger.warning(f"Caption cache unreadable, starting fresh: {e}")
        return {}


def _save_caption_cache(cache: dict[str, str]) -> None:
    CAPTION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CAPTION_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _caption_one_image(client: anthropic.Anthropic, img_path: Path, media_type: str) -> str:
    img_data = base64.standard_b64encode(img_path.read_bytes()).decode()
    resp = client.messages.create(
        model=CAPTION_MODEL,
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_data},
                },
                {"type": "text", "text": CAPTION_PROMPT},
            ],
        }],
    )
    _record_usage(CAPTION_MODEL, resp.usage)
    return resp.content[0].text.strip().replace("\n", " ")


def _caption_all_images(client: anthropic.Anthropic, emails: list[dict]) -> dict[str, str]:
    """Caption every selected image. Returns {path_str: caption}, cached on disk."""
    cache = _load_caption_cache()
    new_count = 0
    usage_start = len(_run_usage)
    t0 = time.perf_counter()
    for email in emails:
        for img in email["images"]:
            key = str(img["path"])
            if key in cache:
                continue
            try:
                cache[key] = _caption_one_image(client, img["path"], img["media_type"])
                new_count += 1
                logger.debug(f"Captioned {img['path'].name}: {cache[key]}")
            except Exception as e:
                logger.warning(f"Caption failed for {img['path']}: {e}")
                cache[key] = ""  # mark attempted; empty caption falls back to subject
    duration = time.perf_counter() - t0
    if new_count:
        _save_caption_cache(cache)
        logger.info(f"Captioned {new_count} new image(s) with {CAPTION_MODEL}")
        new_entries = _run_usage[usage_start:]
        get_timer().record_llm_call(
            "haiku_caption",
            model=CAPTION_MODEL,
            duration_sec=duration,
            tokens_in=sum(e["input_tokens"] for e in new_entries),
            tokens_out=sum(e["output_tokens"] for e in new_entries),
            calls=new_count,
        )
    return cache


def _select_key_images(email_dir: Path, image_names: list[str]) -> list[dict]:
    """Filter images to keep only charts/data (skip logos/banners)."""
    selected = []
    for name in image_names:
        path = email_dir / name
        if not path.exists():
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        size = path.stat().st_size
        if size < MIN_IMAGE_SIZE:
            continue
        selected.append({
            "path": path,
            "name": name,
            "size": size,
            "media_type": _media_type(ext),
        })
        if len(selected) >= MAX_IMAGES_PER_EMAIL:
            break
    return selected


def _build_content_blocks(
    emails: list[dict],
    meritco_entries: list[dict] | None = None,
    captions: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, Path], dict[str, str]]:
    """Build multimodal content blocks for Claude API.

    Returns (blocks, img_map, img_caption) where:
      img_map: {IMG_XX: original_path}
      img_caption: {IMG_XX: short chart description (Haiku-generated or fallback)}
    `captions` maps str(path) → Haiku-generated chart caption (empty string if failed).
    """
    meritco_entries = meritco_entries or []
    captions = captions or {}
    blocks: list[dict] = []
    img_map: dict[str, Path] = {}
    img_caption: dict[str, str] = {}  # IMG_XX → chart caption (or fallback)
    img_counter = 0

    blocks.append({
        "type": "text",
        "text": (
            f"以下是 {len(emails)} 封投研邮件"
            + (f" 以及 {len(meritco_entries)} 条久谦论坛专家纪要（近几天）" if meritco_entries else "")
            + "，请按要求整理为每日摘要：\n"
        ),
    })

    for i, email in enumerate(emails, 1):
        fm = email["frontmatter"]
        subject = fm.get("subject", "Unknown")
        sender = fm.get("sender_name", "")
        addr = fm.get("sender_address", "")
        received = fm.get("received_at", "")

        # Email header
        blocks.append({
            "type": "text",
            "text": (
                f"\n{'='*60}\n"
                f"## 邮件 {i}/{len(emails)}\n"
                f"**标题**: {subject}\n"
                f"**发件人**: {sender} <{addr}>\n"
                f"**时间**: {received}\n"
                f"{'='*60}\n\n"
                f"{email['body']}\n"
            ),
        })

        # Attach key images with sequential IMG_XX IDs
        for img in email["images"]:
            img_counter += 1
            img_id = f"IMG_{img_counter:02d}"
            caption = (captions.get(str(img["path"])) or "").strip()
            label = caption if caption else f"来自《{subject}》"
            try:
                img_data = base64.standard_b64encode(img["path"].read_bytes()).decode()
                blocks.append({
                    "type": "text",
                    "text": f"\n[{img_id}] {label}\n",
                })
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img_data,
                    },
                })
                img_map[img_id] = img["path"]
                img_caption[img_id] = label
            except Exception as e:
                logger.warning(f"Failed to encode image {img['name']}: {e}")

    # Meritco section — render separately with source URLs so LLM can cite
    if meritco_entries:
        blocks.append({
            "type": "text",
            "text": (
                f"\n{'='*70}\n"
                f"# 久谦论坛专家纪要（近 {len({m['date'] for m in meritco_entries})} 天，共 {len(meritco_entries)} 条）\n"
                f"{'='*70}\n"
                "**重要**：以下纪要均来自久谦论坛（meritco-group.com），引用时请使用提供的 source_url。\n"
                "纪要为专家 Q&A 格式，提取关键数据点和结论即可。\n"
            ),
        })
        for j, m in enumerate(meritco_entries, 1):
            fm = m["frontmatter"]
            blocks.append({
                "type": "text",
                "text": (
                    f"\n--- 久谦纪要 {j}/{len(meritco_entries)} ---\n"
                    f"**meritco_id**: {fm.get('id', '')}\n"
                    f"**source_url**: {m.get('source_url') or '(unknown)'}\n"
                    f"**date**: {m.get('date', '')}\n"
                    f"**专家**: {fm.get('sender_name', '')}\n"
                    f"**industry**: {fm.get('industry', '')}\n"
                    f"**tickers**: {fm.get('tickers', [])}\n"
                    f"**title**: {fm.get('subject', '')}\n\n"
                    f"{m['body']}\n"
                ),
            })

    # Final constraint — explicit image inventory (with captions) + reuse prevention
    if img_counter > 0:
        inventory_lines = "\n".join(
            f"- `IMG_{i:02d}`：{img_caption.get(f'IMG_{i:02d}', '?')}"
            for i in range(1, img_counter + 1)
        )
        bound_text = (
            f"\n\n{'='*70}\n"
            f"📋 **可用图片清单（共 {img_counter} 张，每条已附内容描述）**：\n"
            f"{inventory_lines}\n\n"
            f"⛔ **三条硬性规则**：\n"
            f"1. **严禁引用清单外的 ID**（如 IMG_{img_counter+1:02d} 不存在）\n"
            f"2. **每个 IMG_XX 在整个输出中至多引用一次**，不可换 caption 复用同一 ID\n"
            f"3. **只在该 ID 描述的内容与你正在写的段落主题真正匹配时才嵌入**；"
            f"如果某段你想配图但清单里没有内容契合的，用文字描述数据点替代，"
            f"**不要硬塞内容不符的 ID**\n"
            f"{'='*70}\n"
        )
    else:
        bound_text = (
            f"\n\n{'='*70}\n"
            f"📋 **本次输入未提供任何图片**。请勿在输出中使用任何 IMG_XX 引用，全部用文字描述数据点。\n"
            f"{'='*70}\n"
        )
    blocks.append({"type": "text", "text": bound_text})

    return blocks, img_map, img_caption


def _media_type(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
