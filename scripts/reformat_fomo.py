#!/usr/bin/env python3
"""Backfill: reformat existing fomo-therapy email.md files.

New emails are reformatted automatically by storage.save_email; this script is
only for one-off backfills of previously fetched files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.fomo_format import reformat_content  # noqa: E402

ROOT = Path("/Users/zhangxypro/Code/Claude_Workspace/inv_newsletter/data/mail")


def main():
    paths = sorted(ROOT.glob("*/[0-9]*-fomo-therapy-notifications/email.md"))
    dry_run = "--dry-run" in sys.argv
    only = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
    for p in paths:
        if only and only not in str(p):
            continue
        original = p.read_text()
        new = reformat_content(original)
        rel = p.relative_to(ROOT)
        if new == original:
            print(f"unchanged: {rel}")
        elif dry_run:
            print(f"WOULD reformat: {rel}")
        else:
            p.write_text(new)
            print(f"reformatted: {rel}")


if __name__ == "__main__":
    main()
