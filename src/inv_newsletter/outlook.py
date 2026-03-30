"""Outlook REST API email fetching (using OWA session token)."""

import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from inv_newsletter.auth import OutlookBrowser

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_EMAILS = 500


@dataclass
class Email:
    id: str
    subject: str
    sender_name: str
    sender_address: str
    received_at: datetime
    body_html: str
    body_preview: str


@dataclass
class Attachment:
    name: str
    content_type: str
    content_bytes: bytes
    is_inline: bool
    content_id: str  # for cid: mapping in HTML


class OutlookClient:
    def __init__(self, browser: OutlookBrowser):
        self._browser = browser

    def fetch_emails(
        self,
        senders: list[str] | None = None,
        keywords: list[str] | None = None,
        hours_back: int = 24,
        top: int = 50,
    ) -> list[Email]:
        """Fetch emails using Outlook REST API v2.0."""
        session = self._browser.get_session()
        headers = {
            "Authorization": f"Bearer {session.token}",
            "Content-Type": "application/json",
        }

        # Build OData $filter
        filter_parts = []
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        filter_parts.append(f"ReceivedDateTime ge {cutoff}")

        if senders:
            sender_clauses = " or ".join(
                f"From/EmailAddress/Address eq '{s}'" for s in senders
            )
            filter_parts.append(f"({sender_clauses})")

        params: dict = {
            "$filter": " and ".join(filter_parts),
            "$select": "Id,Subject,From,ReceivedDateTime,Body,BodyPreview",
            "$orderby": "ReceivedDateTime desc",
            "$top": top,
        }

        url = f"{session.api_base}/me/messages"
        all_emails: list[Email] = []

        while url and len(all_emails) < MAX_EMAILS:
            response = self._request_with_retry(url, headers, params)
            data = response.json()

            for msg in data.get("value", []):
                all_emails.append(self._parse_message(msg))

            url = data.get("@odata.nextLink")
            params = None

        # Client-side keyword filtering (more reliable than $search + $filter combo)
        if keywords:
            kw_lower = [k.lower() for k in keywords]
            all_emails = [
                e for e in all_emails
                if any(k in e.subject.lower() for k in kw_lower)
            ]

        logger.info(f"Fetched {len(all_emails)} emails (after keyword filter).")
        return all_emails

    def fetch_attachments(self, message_id: str) -> list[Attachment]:
        """Fetch all attachments for a message."""
        session = self._browser.get_session()
        headers = {"Authorization": f"Bearer {session.token}"}
        url = f"{session.api_base}/me/messages/{message_id}/attachments"

        resp = self._request_with_retry(url, headers, None)
        data = resp.json()

        attachments = []
        for item in data.get("value", []):
            raw_bytes = item.get("ContentBytes", "")
            try:
                content = base64.b64decode(raw_bytes) if raw_bytes else b""
            except Exception:
                content = b""
            attachments.append(Attachment(
                name=item.get("Name", "unknown"),
                content_type=item.get("ContentType", "application/octet-stream"),
                content_bytes=content,
                is_inline=item.get("IsInline", False),
                content_id=item.get("ContentId", ""),
            ))

        logger.debug(f"Fetched {len(attachments)} attachments for message.")
        return attachments

    def _request_with_retry(
        self, url: str, headers: dict, params: dict | None
    ) -> requests.Response:
        for attempt in range(MAX_RETRIES):
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                logger.warning(f"Rate limited. Retrying after {retry_after}s...")
                time.sleep(retry_after)
                continue
            if resp.status_code == 401:
                logger.error(f"401 response: {resp.text[:300]}")
                raise RuntimeError(
                    "API returned 401. Token may have expired. "
                    "Delete .browser_state/ and re-run."
                )
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"Failed after {MAX_RETRIES} retries.")

    def _parse_message(self, msg: dict) -> Email:
        # Outlook REST API uses PascalCase field names
        from_info = msg.get("From", {}).get("EmailAddress", {})
        body = msg.get("Body", {})
        received = msg.get("ReceivedDateTime", "")
        return Email(
            id=msg.get("Id", ""),
            subject=msg.get("Subject", "(no subject)"),
            sender_name=from_info.get("Name", ""),
            sender_address=from_info.get("Address", ""),
            received_at=datetime.fromisoformat(received.replace("Z", "+00:00")),
            body_html=body.get("Content", "") if body.get("ContentType") == "HTML" else "",
            body_preview=msg.get("BodyPreview", ""),
        )
