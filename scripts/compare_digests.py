#!/usr/bin/env python3
"""Run the comparison report between baseline digest and refactor_v2 digest.

Usage:
  uv run scripts/compare_digests.py --date 2026-05-12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from inv_newsletter.refactor_v2.compare import render_report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--output-dir", default="output/daily")
    p.add_argument("--baseline-suffix", default="", help="Suffix for baseline file (default: empty → _daily_digest.md)")
    args = p.parse_args()

    output_dir = Path(args.output_dir)
    baseline_path = output_dir / f"{args.date}_daily_digest{args.baseline_suffix}.md"
    v2_path = output_dir / f"{args.date}_daily_digest_refactor_v2.md"
    artifacts = output_dir / args.date / "refactor_v2"
    link_inventory = artifacts / "packets" / "link_inventory.json"
    cross_source = artifacts / "packets" / "cross_source.json"
    cost_ledger = artifacts / "cost_ledger.json"
    report_path = artifacts / "comparison_report.md"

    for path, label in [(baseline_path, "baseline"), (v2_path, "v2"),
                        (link_inventory, "link_inventory"), (cross_source, "cross_source")]:
        if not path.exists():
            print(f"❌ missing {label}: {path}")
            sys.exit(1)

    result = render_report(
        baseline_path=baseline_path,
        v2_path=v2_path,
        link_inventory_path=link_inventory,
        cross_source_path=cross_source,
        cost_ledger_path=cost_ledger,
        output_path=report_path,
    )
    print(f"✅ Comparison report written: {report_path}")
    print(f"  baseline chars: {result['baseline']['density']['char_count']:,}")
    print(f"  v2 chars:       {result['v2']['density']['char_count']:,}")
    print(f"  v2 cost:        ${result['cost'].get('grand_cost_usd', 0):.4f}")


if __name__ == "__main__":
    main()
