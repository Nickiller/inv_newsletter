#!/usr/bin/env python3
"""Stage-2 TL;DR generator — generates `## 今日要点` from a finished digest.

This is the two-stage architecture test harness:
  Stage 1 (existing): main_digest call generates sectors only
  Stage 2 (this script): single LLM call extracts TL;DR from rendered draft

Usage:
    uv run scripts/gen_tldr.py --digest output/daily/2026-05-18_daily_digest.md
    uv run scripts/gen_tldr.py --digest <path> --model claude-opus-4-7
    uv run scripts/gen_tldr.py --digest <path> --write   # prepend into the file
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

TLDR_PROMPT_PATH = Path(__file__).resolve().parents[1] / "src/inv_newsletter/prompts/tldr.md"
TLDR_HEADER_RE = re.compile(r"^## 今日要点\s*\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _price_estimate(model: str, in_tok: int, out_tok: int) -> float:
    pricing = {
        "opus":   (15.00, 75.00),
        "sonnet": (3.00, 15.00),
        "haiku":  (1.00,  5.00),
    }
    for tier, (i, o) in pricing.items():
        if tier in model.lower():
            return in_tok / 1_000_000 * i + out_tok / 1_000_000 * o
    return 0.0


def strip_existing_tldr(digest_md: str) -> str:
    """Remove any existing `## 今日要点` section (until next `## `)."""
    return TLDR_HEADER_RE.sub("", digest_md, count=1).lstrip()


def generate_tldr(digest_body: str, model: str, prompt_text: str) -> tuple[str, dict]:
    """Call Claude with tldr prompt + digest body. Returns (tldr_md, usage_dict)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    user_msg = (
        f"<digest>\n{digest_body.strip()}\n</digest>\n\n"
        "上方 <digest> 是一份当日已完成的投研 digest。请按 system prompt 抽取 `## 今日要点` 速读块。"
    )

    t0 = time.perf_counter()
    chunks: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=4000,
        system=[{"type": "text", "text": prompt_text}],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for txt in stream.text_stream:
            chunks.append(txt)
        final = stream.get_final_message()
    duration = time.perf_counter() - t0

    text = "".join(chunks).strip()
    # Strip ```markdown fences if model added them
    text = re.sub(r"^```(?:markdown)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    usage = {
        "input_tokens": getattr(final.usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(final.usage, "output_tokens", 0) or 0,
        "duration_sec": duration,
        "stop_reason": final.stop_reason,
    }
    return text, usage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--digest", required=True, type=Path,
                        help="Path to digest .md file (e.g. output/daily/2026-05-18_daily_digest.md)")
    parser.add_argument("--model", default="claude-opus-4-7",
                        help="Model ID (default: claude-opus-4-7; try claude-sonnet-4-6 for cheaper)")
    parser.add_argument("--prompt-file", type=Path, default=TLDR_PROMPT_PATH,
                        help=f"TL;DR system prompt (default: {TLDR_PROMPT_PATH})")
    parser.add_argument("--write", action="store_true",
                        help="Prepend generated TL;DR into the digest file (after H1, before first ## sector). Default: print only.")
    args = parser.parse_args()

    if not args.digest.exists():
        print(f"ERROR: digest not found: {args.digest}", file=sys.stderr)
        return 1
    if not args.prompt_file.exists():
        print(f"ERROR: prompt not found: {args.prompt_file}", file=sys.stderr)
        return 1

    digest_md = args.digest.read_text(encoding="utf-8")
    prompt_text = args.prompt_file.read_text(encoding="utf-8")

    digest_body = strip_existing_tldr(digest_md)
    body_chars = len(digest_body)
    print(f"📄 Digest: {args.digest} ({body_chars:,} chars, ~{body_chars // 3:,} tokens)", file=sys.stderr)
    print(f"🤖 Model: {args.model}", file=sys.stderr)
    print(f"📝 Prompt: {args.prompt_file}", file=sys.stderr)
    print(f"⏳ Generating TL;DR...", file=sys.stderr)

    tldr_text, usage = generate_tldr(digest_body, args.model, prompt_text)

    cost = _price_estimate(args.model, usage["input_tokens"], usage["output_tokens"])
    print(
        f"✅ Done in {usage['duration_sec']:.1f}s · "
        f"in {usage['input_tokens']:,} / out {usage['output_tokens']:,} tok · "
        f"${cost:.4f} · stop={usage['stop_reason']}",
        file=sys.stderr,
    )
    print("=" * 70, file=sys.stderr)

    print(tldr_text)

    if args.write:
        # Insert after H1 (# Daily Research Digest ...), before first ## section
        lines = digest_md.split("\n")
        # Strip existing tldr first
        digest_md_clean = strip_existing_tldr(digest_md)
        lines_clean = digest_md_clean.split("\n")
        insert_idx = 0
        for i, ln in enumerate(lines_clean):
            if ln.startswith("## "):
                insert_idx = i
                break
        new_lines = (
            lines_clean[:insert_idx]
            + [tldr_text.strip(), ""]
            + lines_clean[insert_idx:]
        )
        args.digest.write_text("\n".join(new_lines), encoding="utf-8")
        print(f"\n📝 Wrote updated digest with TL;DR prepended → {args.digest}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
