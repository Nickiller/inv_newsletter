"""Scan Outlook for weekly summary emails over the past N days.

Strategy:
  1. Fetch all emails over past N days from a list of suspected weekly senders.
  2. Additionally scan ALL emails over past N days and surface anything whose
     subject contains common 'weekly' patterns (Weekly / Week Ahead / Next Week
     / 一周 / 周报 / 周观察 / 周要点 / 周思考 / etc.)

Output: print grouped table of (sender, subject, date) to stdout.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import datetime

from inv_newsletter.auth import OutlookBrowser
from inv_newsletter.outlook import OutlookClient

WEEKLY_SUBJECT_PATTERNS = [
    "weekly",
    "week ahead",
    "next week",
    "this week",
    "week in review",
    "week wrap",
    "weekend read",
    "周报",
    "周观察",
    "一周",
    "本周",
    "上周",
    "周要点",
    "周思考",
    "周观点",
    "周回顾",
]

# Senders specifically called out by the user
KNOWN_WEEKLY_SENDERS = [
    "keith.murray@bernsteinsg.com",
    "zukinteam@wolferesearch.com",
]

# Plus existing daily senders so we can spot weeklies they may also send
EXISTING_DAILY_SENDERS = [
    "mark.schilsky@jpmorgan.com",
    "jfavuzza@jefferies.com",
    "tyler.seidman@bernsteinsg.com",
    "no-reply@notifications.alphaholic.app",
    "zezhou@notifications.alphaholic.app",
    "skhajuria@wolferesearch.com",
    "joshua.meyers@jpmorgan.com",
]


def matches_weekly(subject: str) -> bool:
    s = subject.lower()
    return any(p in s for p in WEEKLY_SUBJECT_PATTERNS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24 * 10, help="Lookback window")
    parser.add_argument("--top", type=int, default=200, help="Per-page top")
    parser.add_argument("--all", action="store_true",
                        help="Also scan ALL inbox (not just suspected senders) for 'weekly' subject patterns")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    browser = OutlookBrowser()
    client = OutlookClient(browser)

    found: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

    # Pass 1: fetch from known + daily senders, no subject filter — show all subjects
    sender_pool = list(set(KNOWN_WEEKLY_SENDERS + EXISTING_DAILY_SENDERS))
    print(f"\n=== Pass 1: emails from {len(sender_pool)} suspected senders, last {args.hours}h ===\n")
    emails = client.fetch_emails(senders=sender_pool, hours_back=args.hours, top=args.top)
    for e in emails:
        found[e.sender_address].append((e.received_at, e.subject))

    # Print grouped by sender
    for sender in sorted(found):
        msgs = sorted(found[sender], reverse=True)
        weekly_count = sum(1 for _, s in msgs if matches_weekly(s))
        flag = " [HAS WEEKLY]" if weekly_count else ""
        print(f"\n--- {sender} ({len(msgs)} emails, {weekly_count} weekly){flag} ---")
        for dt, subj in msgs[:15]:
            mark = " ⭐" if matches_weekly(subj) else ""
            print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  {subj[:120]}{mark}")

    # Pass 2: scan whole inbox for weekly subject patterns
    if args.all:
        print(f"\n\n=== Pass 2: ALL inbox scan for 'weekly' subjects, last {args.hours}h ===\n")
        all_emails = client.fetch_emails(senders=None, hours_back=args.hours, top=args.top)
        weekly_hits = [e for e in all_emails if matches_weekly(e.subject)]
        # Skip senders already in pool
        novel = [e for e in weekly_hits if e.sender_address not in sender_pool]
        novel.sort(key=lambda e: e.received_at, reverse=True)
        print(f"Total inbox: {len(all_emails)}, weekly-subject hits: {len(weekly_hits)}, "
              f"novel senders: {len(novel)}\n")
        for e in novel[:50]:
            print(f"  {e.received_at.strftime('%Y-%m-%d %H:%M')}  "
                  f"{e.sender_address:<45} {e.subject[:100]}")


if __name__ == "__main__":
    main()
