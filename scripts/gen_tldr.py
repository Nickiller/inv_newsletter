#!/usr/bin/env python3
"""Stage-2 TL;DR generator — thin CLI wrapper around inv_newsletter.tldr.

Usage:
    uv run scripts/gen_tldr.py --digest output/daily/2026-05-18_daily_digest.md
    uv run scripts/gen_tldr.py --digest <path> --model claude-sonnet-4-6
    uv run scripts/gen_tldr.py --digest <path> --write   # prepend into the file
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow `python scripts/gen_tldr.py` to find the local src/ package without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inv_newsletter.tldr import (  # noqa: E402
    TLDR_DEFAULT_MODEL,
    TLDR_PROMPT_PATH,
    generate_tldr,
    prepend_tldr,
    strip_existing_tldr,
)

load_dotenv(override=True)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--digest", required=True, type=Path,
                        help="Path to digest .md file (e.g. output/daily/2026-05-18_daily_digest.md)")
    parser.add_argument("--model", default=TLDR_DEFAULT_MODEL,
                        help=f"Model ID (default: {TLDR_DEFAULT_MODEL}; try claude-sonnet-4-6 for cheaper)")
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
        updated = prepend_tldr(digest_md, tldr_text)
        args.digest.write_text(updated, encoding="utf-8")
        print(f"\n📝 Wrote updated digest with TL;DR prepended → {args.digest}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
