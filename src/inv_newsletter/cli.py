"""CLI entry point: fetch filtered emails and save as Markdown."""

import argparse
import logging
from pathlib import Path

from inv_newsletter.auth import OutlookBrowser
from inv_newsletter.config import load_config
from inv_newsletter.converter import convert_email
from inv_newsletter.outlook import OutlookClient
from inv_newsletter.storage import is_already_fetched, mark_fetched, save_email

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Fetch and save investment emails")
    parser.add_argument("--config", "-c", default="filters.yaml", help="Path to filters config")
    parser.add_argument("--data-dir", "-d", default=None, help="Output directory (default: data/mail)")
    parser.add_argument("--hours", "-H", type=int, default=None, help="Override hours_back")
    parser.add_argument("--dry-run", action="store_true", help="List matching emails without saving")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Load config
    config = load_config(Path(args.config))
    if args.hours:
        config.hours_back = args.hours
    base_dir = Path(args.data_dir) if args.data_dir else config.data_dir
    base_dir.mkdir(parents=True, exist_ok=True)

    # Authenticate
    browser = OutlookBrowser()
    client = OutlookClient(browser)

    # Fetch emails matching all filters
    senders = config.all_senders
    keywords = config.all_keywords or None
    logger.info(f"Fetching emails: {len(senders)} senders, {len(keywords or [])} keywords, last {config.hours_back}h")

    emails = client.fetch_emails(
        senders=senders,
        keywords=keywords,
        hours_back=config.hours_back,
    )
    logger.info(f"Found {len(emails)} matching emails.")

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN: {len(emails)} emails would be fetched")
        print(f"{'='*60}")
        for i, email in enumerate(emails, 1):
            already = " [SKIP: already fetched]" if is_already_fetched(email.id, base_dir) else ""
            print(f"\n[{i}] {email.subject}{already}")
            print(f"    From: {email.sender_name} <{email.sender_address}>")
            print(f"    Time: {email.received_at.strftime('%Y-%m-%d %H:%M')}")
        return

    # Process each email
    saved = 0
    skipped = 0
    errors = 0
    for email in emails:
        if is_already_fetched(email.id, base_dir):
            skipped += 1
            continue

        try:
            attachments = client.fetch_attachments(email.id)
            result = convert_email(email.body_html, attachments, email.subject)
            email_dir = save_email(email, result, base_dir)
            mark_fetched(email.id, str(email_dir), base_dir)
            saved += 1
        except Exception as e:
            errors += 1
            logger.error(f"Failed to process '{email.subject}': {e}")

    print(f"\nDone. Saved: {saved}, Skipped: {skipped}, Errors: {errors}")


if __name__ == "__main__":
    main()
