#!/usr/bin/env python3
"""CLI entry point for the refactor_v2 daily digest pipeline.

Usage:
  uv run scripts/run_digest_v2.py --date 2026-05-12
  uv run scripts/run_digest_v2.py --date 2026-05-12 --model claude-opus-4-7

This does NOT touch the existing cli.py / launchd path. Outputs go to:
  output/daily/<DATE>_daily_digest_refactor_v2.md
  output/daily/<DATE>/refactor_v2/{packets,helpers,sectors,cost_ledger.json,audit_report.md}
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make the package importable when running from repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from inv_newsletter.refactor_v2.pipeline import DEFAULT_MODEL, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="refactor_v2 digest pipeline")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--data-mail-dir", default="data/mail", help="Mail data root")
    parser.add_argument("--meritco-dir", default="data/meritco", help="Meritco data root")
    parser.add_argument("--meritco-days", type=int, default=3, help="Days of meritco to include")
    parser.add_argument("--output-dir", default="output/daily", help="Output root")
    parser.add_argument("--filters-yaml", default="filters.yaml", help="Filters config path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Drafting model")
    parser.add_argument("--triage-model", default=None, help="Override Stage A model")
    parser.add_argument("--catalyst-model", default=None, help="Override Stage C model")
    parser.add_argument("--max-tokens-per-sector", type=int, default=8000)
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    result = run_pipeline(
        target_date=args.date,
        data_mail_dir=Path(args.data_mail_dir),
        meritco_dir=Path(args.meritco_dir),
        meritco_days=args.meritco_days,
        output_dir=Path(args.output_dir),
        filters_yaml=Path(args.filters_yaml),
        model=args.model,
        triage_model=args.triage_model,
        catalyst_model=args.catalyst_model,
        max_tokens_per_sector=args.max_tokens_per_sector,
    )

    print("\n" + "=" * 72)
    print("✅ Pipeline complete")
    print("=" * 72)
    print(f"Digest:        {result['digest_path']}")
    print(f"Artifacts:     {result['artifacts_dir']}")
    print(f"Audit report:  {result['audit_path']}")
    print(f"Duration:      {result['duration_sec']}s")
    print(f"Sell-side link coverage:  {result['stats']['sell_side_link_coverage_pct']}%")
    print(f"Anchor-trap coverage:     {result['stats']['anchor_trap_coverage_pct']}%")
    print(f"Suspicious cross-source claims: {result['stats']['suspicious_cross_source_claims']}")
    print(f"Total cost:    ${result['cost_ledger']['grand_cost_usd']:.4f}")


if __name__ == "__main__":
    main()
