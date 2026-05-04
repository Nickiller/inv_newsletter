"""Auto-monitor: poll for emails, summarize when enough sources arrive."""

import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from inv_newsletter.config import AppConfig, FilterGroup, MonitorConfig

logger = logging.getLogger(__name__)

STATE_FILE = ".monitor_state.json"


def run_monitor(config: AppConfig, base_dir: Path) -> None:
    """Main entry: fetch, check sources, summarize if ready."""
    mon = config.monitor
    tz = ZoneInfo(mon.timezone)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    hour = now.hour

    # Before polling window? (deadline handled inside _should_summarize)
    if hour < mon.start_hour:
        logger.debug(f"Before start ({mon.start_hour}:00), skipping")
        return

    state = _load_state(base_dir)
    day_state = state.get(today, {})

    # Already summarized today?
    if day_state.get("summarized"):
        logger.info(f"Already summarized today, skipping")
        return

    # Fetch new emails
    new_saved = _do_fetch_safe(config, base_dir)

    # Scan received sources
    date_dir = base_dir / today
    if not date_dir.is_dir():
        logger.info(f"No emails yet for {today}")
        _save_state(state, base_dir)
        return

    received = _scan_received_sources(date_dir, config.filters)
    received_names = [name for name, hit in received.items() if hit]
    received_count = len(received_names)
    total_count = len(received)

    # Log status line
    source_status = " ".join(
        f"{name}({'Y' if hit else 'N'})" for name, hit in received.items()
    )

    # Update state
    prev_sources = set(day_state.get("sources_received", []))
    has_new = set(received_names) - prev_sources
    day_state["sources_received"] = received_names
    if has_new:
        day_state["last_new_email_at"] = now.isoformat()
    if "first_check_at" not in day_state:
        day_state["first_check_at"] = now.isoformat()
    state[today] = day_state

    # Decision
    should, reason = _should_summarize(received, mon, day_state, now)

    logger.info(
        f"Sources: {source_status} [{received_count}/{total_count}] | Action: {reason}"
    )

    if should:
        try:
            from inv_newsletter.summarizer import summarize_daily

            sum_cfg = config.summarization
            output_path = summarize_daily(
                data_dir=base_dir,
                output_dir=sum_cfg.output_dir,
                target_date=today,
                model=sum_cfg.model,
                max_tokens=sum_cfg.max_tokens,
            )
            day_state["summarized"] = True
            day_state["summarized_at"] = datetime.now(tz).isoformat()
            day_state["summary_path"] = str(output_path)
            logger.info(f"Digest saved -> {output_path}")
            _notify_user(f"Daily digest ready: {received_count} sources summarized")
        except Exception as e:
            logger.error(f"Summarization failed: {e}")

    _save_state(state, base_dir)


def _scan_received_sources(
    date_dir: Path, filters: list[FilterGroup]
) -> dict[str, bool]:
    """Match emails in date_dir against filter groups by sender_address."""
    received_senders: set[str] = set()
    for email_md in date_dir.glob("*/email.md"):
        sender = _parse_frontmatter_sender(email_md)
        if sender:
            received_senders.add(sender.lower())

    return {
        fg.name: any(s.lower() in received_senders for s in fg.senders)
        for fg in filters
    }


def _parse_frontmatter_sender(email_md: Path) -> str | None:
    """Fast extraction of sender_address from YAML frontmatter."""
    try:
        in_frontmatter = False
        with open(email_md, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped == "---":
                    if not in_frontmatter:
                        in_frontmatter = True
                        continue
                    else:
                        break  # End of frontmatter
                if in_frontmatter and line.startswith("sender_address:"):
                    return line.split(":", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _should_summarize(
    received: dict[str, bool],
    mon: MonitorConfig,
    day_state: dict,
    now: datetime,
) -> tuple[bool, str]:
    """Decide whether to summarize now."""
    received_count = sum(1 for v in received.values() if v)
    total_count = len(received)
    is_weekend = now.weekday() >= 5
    min_sources = mon.weekend_min_sources if is_weekend else mon.weekday_min_sources

    # All sources received
    if received_count == total_count:
        return True, f"all {total_count} sources received, summarizing"

    # Past deadline
    if now.hour >= mon.deadline_hour:
        if received_count >= 1:
            return True, f"deadline reached with {received_count}/{total_count}, summarizing"
        return False, "deadline reached but no emails"

    # Threshold met + grace period
    if received_count >= min_sources:
        last_new = day_state.get("last_new_email_at")
        if last_new:
            last_new_dt = datetime.fromisoformat(last_new)
            elapsed = (now - last_new_dt).total_seconds() / 60
            if elapsed >= mon.grace_minutes:
                return True, f"grace elapsed ({int(elapsed)}min), summarizing"
            remaining = int(mon.grace_minutes - elapsed)
            return False, f"threshold met, grace {remaining}min remaining"
        return False, "threshold met, grace started"

    return False, f"waiting ({received_count}/{total_count})"


def _do_fetch_safe(config: AppConfig, base_dir: Path) -> int:
    """Fetch emails, catching token/network errors gracefully."""
    from inv_newsletter.auth import OutlookBrowser
    from inv_newsletter.converter import convert_email
    from inv_newsletter.outlook import OutlookClient
    from inv_newsletter.storage import is_already_fetched, mark_fetched, save_email

    base_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    try:
        browser = OutlookBrowser()
        client = OutlookClient(browser)

        emails = client.fetch_emails(
            senders=config.all_senders,
            keywords=config.all_keywords or None,
            exclude_keywords=config.all_exclude_keywords or None,
            hours_back=config.hours_back,
        )

        for email in emails:
            if is_already_fetched(email.id, base_dir):
                continue
            try:
                attachments = client.fetch_attachments(email.id)
                result = convert_email(email.body_html, attachments, email.subject)
                email_dir = save_email(email, result, base_dir)
                mark_fetched(email.id, str(email_dir), base_dir)
                saved += 1
            except Exception as e:
                logger.error(f"Failed to process '{email.subject}': {e}")
    except RuntimeError as e:
        if "token" in str(e).lower() or "401" in str(e):
            logger.error(f"Token expired, manual login needed: {e}")
            _notify_user("inv-newsletter: Token expired, run 'inv-newsletter' to re-login")
        else:
            logger.error(f"Fetch error: {e}")
    except Exception as e:
        logger.error(f"Fetch error: {e}")

    if saved:
        logger.info(f"Fetched {saved} new email(s)")
    return saved


def _load_state(base_dir: Path) -> dict:
    path = base_dir / STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict, base_dir: Path) -> None:
    # Prune entries older than 7 days
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    pruned = {k: v for k, v in state.items() if k >= cutoff}

    path = base_dir / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pruned, indent=2, ensure_ascii=False), encoding="utf-8")


def _notify_user(message: str) -> None:
    """Send macOS notification."""
    try:
        subprocess.run(
            [
                "osascript", "-e",
                f'display notification "{message}" with title "inv-newsletter"',
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass
