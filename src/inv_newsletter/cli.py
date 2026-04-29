"""CLI entry point: fetch filtered emails and optionally summarize."""

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from inv_newsletter.config import load_config

logger = logging.getLogger(__name__)


def main():
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(description="Fetch and summarize investment emails")
    parser.add_argument("--config", "-c", default="filters.yaml", help="Path to filters config")
    parser.add_argument("--data-dir", "-d", default=None, help="Data directory (default: data/mail)")
    parser.add_argument("--hours", "-H", type=int, default=None, help="Override hours_back")
    parser.add_argument("--dry-run", action="store_true", help="List matching emails without saving")
    parser.add_argument("--summarize", "-s", action="store_true", help="Fetch emails then summarize")
    parser.add_argument("--summarize-only", "-S", action="store_true", help="Summarize existing emails (no fetch)")
    parser.add_argument("--date", default=None, help="Target date for summary (YYYY-MM-DD)")
    parser.add_argument("--monitor", "-m", action="store_true",
                        help="Auto-monitor: fetch, check sources, summarize when ready")
    parser.add_argument("--meritco", action="store_true",
                        help="Fetch Meritco (久谦) forum minutes for the target date")
    parser.add_argument("--meritco-dates", default=None,
                        help="Comma-separated dates to fetch Meritco minutes (e.g. 2026-04-23,2026-04-24)")
    parser.add_argument("--exclude-industry", default=None,
                        help="Comma-separated industry keywords to skip (e.g. 医疗,医药,健康)")
    parser.add_argument("--meritco-days", type=int, default=3,
                        help="Number of past days of Meritco minutes to include in daily summary (default 3)")
    parser.add_argument("--no-auto-meritco", action="store_true",
                        help="Skip auto-fetching today's Meritco minutes when summarizing")
    parser.add_argument("--weekly", action="store_true",
                        help="Generate weekly digest (Mon..Sun) — fetches weekly emails + meritco, cross-checks daily")
    parser.add_argument("--week-end", default=None,
                        help="Sunday date for weekly digest (YYYY-MM-DD). Default: most recent Sunday.")
    parser.add_argument("--publish", "-p", action="store_true",
                        help="Publish digest to Lark/Feishu after summarizing (or for existing .md)")
    parser.add_argument("--publish-file", default=None,
                        help="Publish a specific markdown file to Lark (skips fetch & summarize)")
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

    # Monitor mode
    if args.monitor:
        from inv_newsletter.monitor import run_monitor
        run_monitor(config, base_dir)
        return

    # Weekly mode
    if args.weekly:
        _do_weekly(config, base_dir, args.week_end)
        return

    # Publish-file shortcut: just publish an existing .md, skip everything else
    if args.publish_file:
        _do_publish(Path(args.publish_file), config.summarization.lark_folder_token)
        return

    # Fetch emails (unless --summarize-only)
    if not args.summarize_only:
        _do_fetch(config, base_dir, args.dry_run)

    # Fetch Meritco minutes
    exclude_industries = [s.strip() for s in args.exclude_industry.split(",")] if args.exclude_industry else None
    if args.meritco_dates and not args.dry_run:
        for d in [s.strip() for s in args.meritco_dates.split(",")]:
            _do_meritco(d, exclude_industries)
    elif args.meritco and not args.dry_run:
        _do_meritco(args.date, exclude_industries)
    elif (args.summarize or args.summarize_only) and not args.dry_run and not args.no_auto_meritco:
        # Auto-fetch today's meritco when summarizing (so the past-N-days window is fresh)
        try:
            _do_meritco(args.date, exclude_industries)
        except Exception as e:
            logger.warning(f"Auto meritco fetch failed (continuing without): {e}")

    # Summarize (if --summarize or --summarize-only)
    summary_path = None
    if (args.summarize or args.summarize_only) and not args.dry_run:
        summary_path = _do_summarize(config, base_dir, args.date, args.meritco_days)

    # Publish to Lark
    if args.publish and not args.dry_run:
        if summary_path is None:
            # Find the latest digest matching --date or most recent
            sum_cfg = config.summarization
            out_dir = Path(sum_cfg.output_dir)
            if args.date:
                summary_path = out_dir / f"{args.date}_daily_digest.md"
            else:
                candidates = sorted(out_dir.glob("*_daily_digest.md"), reverse=True)
                summary_path = candidates[0] if candidates else None
        if summary_path and summary_path.exists():
            _do_publish(summary_path, config.summarization.lark_folder_token)
        else:
            logger.error(f"No digest file found to publish: {summary_path}")


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


def _do_weekly(config, base_dir: Path, week_end_str: str | None):
    """Fetch weekly emails + meritco for the week, then summarize."""
    from datetime import date, datetime, timedelta

    from inv_newsletter.auth import OutlookBrowser
    from inv_newsletter.converter import convert_email
    from inv_newsletter.meritco import MERITCO_DATA_DIR, fetch_meritco_minutes
    from inv_newsletter.outlook import OutlookClient
    from inv_newsletter.storage import is_already_fetched, mark_fetched, save_email
    from inv_newsletter.weekly import summarize_weekly

    if not config.weekly_filters:
        raise RuntimeError("No weekly_filters defined in filters.yaml")

    # Resolve week_end (default: most recent Sunday)
    if week_end_str:
        week_end = datetime.strptime(week_end_str, "%Y-%m-%d").date()
    else:
        today = date.today()
        days_since_sun = (today.weekday() + 1) % 7
        week_end = today - timedelta(days=days_since_sun)
    week_start = week_end - timedelta(days=6)
    logger.info(f"Weekly window: {week_start} → {week_end}")

    # Step 1: fetch weekly emails
    weekly_senders = []
    weekly_keywords = []
    for fg in config.weekly_filters:
        weekly_senders.extend(fg.senders)
        weekly_keywords.extend(fg.keywords)
    weekly_senders = list(set(weekly_senders))
    weekly_keywords = list(set(weekly_keywords)) or None

    base_dir.mkdir(parents=True, exist_ok=True)
    browser = OutlookBrowser()
    client = OutlookClient(browser)

    # Hours back: from Monday 00:00 of the week to now (extra buffer)
    now_utc = datetime.utcnow()
    monday_utc = datetime.combine(week_start, datetime.min.time())
    hours_back = max(int((now_utc - monday_utc).total_seconds() / 3600) + 12, 24)
    logger.info(f"Fetching weekly emails: {len(weekly_senders)} senders, last {hours_back}h")

    emails = client.fetch_emails(
        senders=weekly_senders, keywords=weekly_keywords, hours_back=hours_back, top=200
    )
    logger.info(f"Found {len(emails)} matching weekly emails")
    saved = skipped = errors = 0
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
    print(f"Weekly fetch done. Saved: {saved}, Skipped: {skipped}, Errors: {errors}")

    # Step 2: backfill meritco for the week (skip days already populated)
    exclude = ["医疗", "医药", "健康"]
    cur = week_start
    while cur <= week_end:
        d_str = cur.isoformat()
        meritco_date_dir = MERITCO_DATA_DIR / d_str
        if not meritco_date_dir.exists() or not any(meritco_date_dir.glob("*.md")):
            try:
                fetch_meritco_minutes(MERITCO_DATA_DIR, target_date=d_str, exclude_industries=exclude)
            except Exception as e:
                logger.warning(f"Meritco fetch failed for {d_str}: {e}")
        cur += timedelta(days=1)

    # Step 3: summarize
    sum_cfg = config.summarization
    output_dir = Path(sum_cfg.output_dir).parent / "weekly"
    out_path = summarize_weekly(
        mail_dir=base_dir,
        meritco_dir=MERITCO_DATA_DIR,
        daily_digest_dir=Path(sum_cfg.output_dir),
        weekly_senders=set(weekly_senders),
        output_dir=output_dir,
        week_end=week_end,
        model=sum_cfg.model,
        max_tokens=sum_cfg.max_tokens,
    )
    print(f"\nSaved weekly digest to: {out_path}")
    return out_path


def _do_meritco(target_date: str | None, exclude_industries: list[str] | None = None):
    from inv_newsletter.meritco import MERITCO_DATA_DIR, fetch_meritco_minutes

    saved = fetch_meritco_minutes(MERITCO_DATA_DIR, target_date=target_date, exclude_industries=exclude_industries)
    print(f"\nMeritco: saved {len(saved)} minutes for {target_date}")


def _do_summarize(config, base_dir: Path, target_date: str | None, meritco_days: int = 3):
    from inv_newsletter.meritco import MERITCO_DATA_DIR
    from inv_newsletter.summarizer import summarize_daily

    sum_cfg = config.summarization
    output_path = summarize_daily(
        data_dir=base_dir,
        output_dir=sum_cfg.output_dir,
        target_date=target_date,
        model=sum_cfg.model,
        max_tokens=sum_cfg.max_tokens,
        meritco_dir=MERITCO_DATA_DIR if MERITCO_DATA_DIR.exists() else None,
        meritco_days=meritco_days,
    )

    print(f"\nSaved to: {output_path}")
    return output_path


def _do_publish(md_path: Path, folder_token: str | None = None):
    import re as _re
    from inv_newsletter.lark_publisher import publish_digest

    logger.info(f"Publishing to Lark: {md_path}")
    result = publish_digest(md_path, folder_token=folder_token)
    doc_url = result["doc_url"]
    print(f"\n📄 Lark doc created: {doc_url}")

    # WeChat-shareable message: detect weekly vs daily by filename suffix
    stem = md_path.stem
    is_weekly = "weekly_digest" in stem
    m = _re.search(r"(\d{2})(\d{2}-\d{2}-\d{2})", stem)
    date_str = m.group(2) if m else stem
    if is_weekly:
        label, prefix = "Weekly Digest", f"本周[周末 {date_str}]"
    else:
        label, prefix = "Daily Digest", f"今日[{date_str}]"
    print("\n💬 微信分享文案：")
    print(f"{prefix} {label}已经生成，点击如下链接查看：{doc_url}")


if __name__ == "__main__":
    main()
