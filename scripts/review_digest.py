#!/usr/bin/env python3
"""De-AI-style review pass — thin CLI wrapper around inv_newsletter.reviewer.

Usage:
    uv run scripts/review_digest.py --digest output/daily/2026-06-05_daily_digest_v3.md
    uv run scripts/review_digest.py --digest <path> --model claude-opus-4-7
    uv run scripts/review_digest.py --digest <path> --write   # overwrite the file in place
    uv run scripts/review_digest.py --digest <path> --out <path>  # write reviewed copy elsewhere

Default: print the reviewed digest to stdout + a safety-gate report to stderr.
Never mutates the input unless --write is passed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow `python scripts/review_digest.py` to find the local src/ package without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inv_newsletter.reviewer import (  # noqa: E402
    REVIEW_DEFAULT_MODEL,
    REVIEW_PROMPT_PATH,
    naturalize,
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
                        help="Path to digest .md file")
    parser.add_argument("--model", default=REVIEW_DEFAULT_MODEL,
                        help=f"Model ID (default: {REVIEW_DEFAULT_MODEL})")
    parser.add_argument("--prompt-file", type=Path, default=REVIEW_PROMPT_PATH,
                        help=f"Reviewer system prompt (default: {REVIEW_PROMPT_PATH})")
    parser.add_argument("--write", action="store_true",
                        help="Overwrite the input digest in place with the reviewed version.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write reviewed digest to this path instead of stdout.")
    args = parser.parse_args()

    if not args.digest.exists():
        print(f"ERROR: digest not found: {args.digest}", file=sys.stderr)
        return 1
    if not args.prompt_file.exists():
        print(f"ERROR: prompt not found: {args.prompt_file}", file=sys.stderr)
        return 1

    digest_md = args.digest.read_text(encoding="utf-8")
    prompt_text = args.prompt_file.read_text(encoding="utf-8")

    chars = len(digest_md)
    print(f"📄 Digest: {args.digest} ({chars:,} chars, ~{chars // 3:,} tokens)", file=sys.stderr)
    print(f"🤖 Model: {args.model}", file=sys.stderr)
    print(f"📝 Prompt: {args.prompt_file}", file=sys.stderr)
    print("⏳ Reviewing (去 AI 味儿)...", file=sys.stderr)

    out_md, usage = naturalize(
        digest_md, args.model, prompt_text,
        logger=lambda m: print(m, file=sys.stderr),
    )

    cost = _price_estimate(args.model, usage["input_tokens"], usage["output_tokens"])
    # before/after deltas for a quick eyeball
    em_before, em_after = digest_md.count("——"), out_md.count("——")
    print(
        f"✅ Done in {usage['duration_sec']:.1f}s · "
        f"in {usage['input_tokens']:,} / out {usage['output_tokens']:,} tok · "
        f"${cost:.4f} · stop={usage['stop_reason']}",
        file=sys.stderr,
    )
    print(f"🔒 Safety gate: {usage['gate']}", file=sys.stderr)
    print(f"   used_review={usage['used_review']} · chars {len(digest_md):,}→{len(out_md):,} · "
          f"破折号 {em_before}→{em_after}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    if args.write:
        args.digest.write_text(out_md, encoding="utf-8")
        print(f"📝 Overwrote {args.digest} with reviewed digest", file=sys.stderr)
    elif args.out:
        args.out.write_text(out_md, encoding="utf-8")
        print(f"📝 Wrote reviewed digest → {args.out}", file=sys.stderr)
    else:
        print(out_md)

    return 0 if usage["safe"] else 2


if __name__ == "__main__":
    sys.exit(main())
