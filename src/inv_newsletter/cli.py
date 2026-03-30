"""CLI entry point: fetch filtered emails and optionally summarize."""

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from inv_newsletter.config import load_config

logger = logging.getLogger(__name__)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Fetch and summarize investment emails")
    parser.add_argument("--config", "-c", default="filters.yaml", help="Path to filters config")
    parser.add_argument("--data-dir", "-d", default=None, help="Data directory (default: data/mail)")
    parser.add_argument("--hours", "-H", type=int, default=None, help="Override hours_back")
    parser.add_argument("--dry-run", action="store_true", help="List matching emails without saving")
    parser.add_argument("--summarize", "-s", action="store_true", help="Fetch emails then summarize")
    parser.add_argument("--summarize-only", "-S", action="store_true", help="Summarize existing emails (no fetch)")
    parser.add_argument("--date", default=None, help="Target date for summary (YYYY-MM-DD)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    config = load_config(Path(args.config))
    if args.hours:
        config.hours_back = args.hours
    base_dir = Path(args.data_dir) if args.data_dir else config.data_dir

    # Fetch emails (unless --summarize-only)
    if not args.summarize_only:
        _do_fetch(config, base_dir, args.dry_run)

    # Summarize (if --summarize or --summarize-only)
    if (args.summarize or args.summarize_only) and not args.dry_run:
        _do_summarize(config, base_dir, args.date)


def _do_fetch(config, base_dir: Path, dry_run: bool):
    from inv_newsletter.auth import OutlookBrowser
    from inv_newsletter.converter import convert_email
    from inv_newsletter.outlook import OutlookClient
    from inv_newsletter.storage import is_already_fetched, mark_fetched, save_email

    base_dir.mkdir(parents=True, exist_ok=True)

    browser = OutlookBrowser()
    client = OutlookClient(browser)

    senders = config.all_senders
    keywords = config.all_keywords or None
    logger.info(f"Fetching emails: {len(senders)} senders, {len(keywords or [])} keywords, last {config.hours_back}h")

    emails = client.fetch_emails(
        senders=senders,
        keywords=keywords,
        hours_back=config.hours_back,
    )
    logger.info(f"Found {len(emails)} matching emails.")

    if dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN: {len(emails)} emails would be fetched")
        print(f"{'='*60}")
        for i, email in enumerate(emails, 1):
            already = " [SKIP]" if is_already_fetched(email.id, base_dir) else ""
            print(f"\n[{i}] {email.subject}{already}")
            print(f"    From: {email.sender_name} <{email.sender_address}>")
            print(f"    Time: {email.received_at.strftime('%Y-%m-%d %H:%M')}")
        return

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

    print(f"\nFetch done. Saved: {saved}, Skipped: {skipped}, Errors: {errors}")


def _do_summarize(config, base_dir: Path, target_date: str | None):
    from inv_newsletter.summarizer import summarize_daily

    sum_cfg = config.summarization
    output_path = summarize_daily(
        data_dir=base_dir,
        output_dir=sum_cfg.output_dir,
        target_date=target_date,
        model=sum_cfg.model,
        max_tokens=sum_cfg.max_tokens,
    )

    # Print digest to terminal
    digest = output_path.read_text(encoding="utf-8")
    print(f"\n{'='*60}")
    print(digest)
    print(f"{'='*60}")
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
