"""Strip subscriber-tracking wrappers from links in newsletter emails.

Newsletter platforms rewrite every link into a per-recipient click-tracking
URL. Published digests must not carry those (they identify the subscriber who
forwarded the content). This module unwraps them to the original target:

- Substack ``substack.com/redirect/2/<JWT>``: target is in the JWT payload
  (``e``) — decoded locally, no network.
- Substack ``substack.com/redirect/<uuid>?j=<subscriber>``: target is only
  known server-side — resolved with ``j`` removed (anonymous request).
- Resend click tracking ``*.resend-clicks-a.com/CL0/<urlencoded>/...``
  (FOMO Therapy): target decoded from the path.

Afterwards subscriber params (``r``, ``token``, ``utm_*``) are dropped from
Substack-hosted targets, and links that cannot be made anonymous, point to a
private Slack workspace, or are Substack account actions (unsubscribe etc.)
are dropped (``None`` → caller keeps the link text only).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

RESOLVE_TIMEOUT = 10
RESOLVE_RETRIES = 4
RESOLVE_PAUSE = 0.5  # seconds between successful lookups — Substack rate-limits (429)
_UUID_RE = re.compile(r"^/redirect/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$")
_SUBSTACK_PARAMS = {"r", "token", "triedredirect", "isfreemail", "publication_id", "post_id"}


def _is_substack_host(host: str) -> bool:
    host = (host or "").lower()
    return host == "substack.com" or host.endswith(".substack.com") or host.endswith("tmtbreakout.com")


def clean_tracking_url(url: str) -> str | None:
    """Return the anonymous target of ``url``; ``None`` if the link should be dropped."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    host = (parsed.hostname or "").lower()

    if host == "substack.com" and parsed.path.startswith("/redirect/"):
        target = _unwrap_substack_redirect(parsed)
        if target is None:
            return None
        return clean_tracking_url(target) if target != url else None

    if host.endswith("resend-clicks-a.com") and parsed.path.startswith("/CL0/"):
        encoded = parsed.path[len("/CL0/"):].split("/", 1)[0]
        return clean_tracking_url(unquote(encoded))

    if host == "app.slack.com" or host.endswith(".slack.com"):
        return None  # private workspace thread — useless to readers, leaks membership

    if _is_substack_host(host):
        if parsed.path.startswith(("/action/", "/app-link/")) or "/subscribe" in parsed.path:
            return None  # unsubscribe / manage-subscription / open-in-app chrome
        return _strip_params(parsed, substack=True)

    return _strip_params(parsed, substack=False)


def _unwrap_substack_redirect(parsed) -> str | None:
    path = parsed.path
    if path.startswith("/redirect/2/"):
        token = path[len("/redirect/2/"):].split("/", 1)[0]
        payload = _jwt_payload(token)
        target = payload.get("e") if payload else None
        if not target:
            logger.warning(f"Undecodable Substack redirect dropped: {path[:60]}")
        return target
    if _UUID_RE.match(path):
        return _resolve_anonymous(f"https://substack.com{path.rstrip('/')}")
    logger.warning(f"Unknown Substack redirect format dropped: {path[:60]}")
    return None


def _jwt_payload(token: str) -> dict | None:
    """Decode the JSON segment of a JWT-ish token (Substack uses both
    ``header.payload.sig`` and bare ``payload.sig``)."""
    for part in token.split("."):
        seg = part + "=" * (-len(part) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(seg))
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "e" in data:
            return data
    return None


_resolved: dict[str, str] = {}  # success-only cache (failures must be retryable)


def _resolve_anonymous(url: str) -> str | None:
    """Follow one redirect hop without any subscriber token (retries on 429)."""
    if url in _resolved:
        return _resolved[url]
    for attempt in range(RESOLVE_RETRIES):
        try:
            resp = requests.get(url, allow_redirects=False, timeout=RESOLVE_TIMEOUT, stream=True)
            resp.close()
        except requests.RequestException as e:
            logger.warning(f"Redirect resolve failed ({e}); link dropped: {url}")
            return None
        location = resp.headers.get("Location")
        if resp.status_code in (301, 302, 303, 307, 308) and location:
            _resolved[url] = location
            time.sleep(RESOLVE_PAUSE)
            return location
        if resp.status_code == 429 and attempt < RESOLVE_RETRIES - 1:
            wait = _retry_after(resp.headers.get("Retry-After"), default=2 ** (attempt + 1))
            time.sleep(wait)
            continue
        break
    logger.warning(f"Redirect resolve got HTTP {resp.status_code}; link dropped: {url}")
    return None


def _retry_after(value: str | None, default: float) -> float:
    try:
        return min(float(value), 30.0) if value else default
    except ValueError:
        return default


def _strip_params(parsed, substack: bool) -> str:
    if not parsed.query:
        return urlunparse(parsed)
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and not (substack and k.lower() in _SUBSTACK_PARAMS)
    ]
    return urlunparse(parsed._replace(query=urlencode(kept)))
