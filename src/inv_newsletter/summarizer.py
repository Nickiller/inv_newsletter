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

from .cost import (
    _estimate_tokens_from_text,
    _format_cost_report,
    _run_usage,
)
from .images import (
    _caption_all_images,
    _embed_images,
    _select_key_images,
    _validate_image_refs,
)
from .postprocess import (
    _drift_audit,
    _reorder_industries_within_section,  # noqa: F401  (re-exported for tests)
    _reorder_sections,
    _write_drift_logs,
)
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

# Token-usage accounting and cost estimation live in cost.py (imported above:
# _estimate_tokens_from_text, _format_cost_report, _run_usage). _run_usage is
# mutated in place (.clear()/.append()/slice reads) so the imported name stays
# bound to the same list object as cost._run_usage.

MERITCO_URL_TEMPLATE = "https://research.meritco-group.com/forum?forumType=2&forumId={id}"
MERITCO_EXCLUDED_INDUSTRIES = (
    "医疗", "医药", "健康", "创新药", "生物科技", "生物医药", "制药", "生命科学"
)

# Image handling (selection, Haiku captioning, ref validation, embedding) lives
# in images.py; the functions called from here are imported above.
_PROMPTS_DIR = Path(__file__).parent / "prompts"

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
    meritco_days: int = 1,
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

        # Drift audit: detect ticker headings in the wrong sector + tickers not in taxonomy.
        # Findings go to logs/ only — never into the published digest.
        report = _drift_audit(digest)
        _write_drift_logs(report, target_date, Path("logs"))
        if report["misclassified"] or report["unmapped"]:
            logger.info(
                f"Audit: misclassified={len(report['misclassified'])}, "
                f"unmapped={len(report['unmapped'])} — see logs/"
            )
        else:
            logger.info("Audit: clean (no drift, no unmapped tickers)")

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
