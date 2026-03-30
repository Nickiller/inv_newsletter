"""Playwright-based OWA access: intercept email data directly from OWA API responses."""

import base64
import json
import logging
import time
from pathlib import Path
from dataclasses import dataclass, field

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BROWSER_STATE_DIR = Path(".browser_state")
TOKEN_CACHE_FILE = Path(".token_cache/owa_token.json")
OWA_URL = "https://outlook.office365.com/mail/"

# Refresh token when less than this many seconds remain
TOKEN_REFRESH_THRESHOLD = 30 * 60  # 30 minutes


def _get_token_expiry(token: str) -> float | None:
    """Decode JWT exp claim. Returns Unix timestamp or None."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.b64decode(payload))
        return claims.get("exp")
    except Exception:
        return None


@dataclass
class OWASession:
    """Holds captured OWA API token and endpoint info."""
    token: str
    api_base: str
    expires_at: float = 0  # Unix timestamp
    headers: dict = field(default_factory=dict)


class OutlookBrowser:
    """Opens OWA via Playwright, captures API token for OWA REST API calls.

    Token lifecycle:
    1. Check token cache → use if >30 min remaining
    2. If token expiring soon or expired → headless refresh (silent, ~3s)
    3. If browser session also expired → visible browser for manual login
    """

    def __init__(self):
        self._session: OWASession | None = None

    def get_session(self) -> OWASession:
        # If we have a session in memory, check if it needs refresh
        if self._session:
            remaining = self._session.expires_at - time.time()
            if remaining > TOKEN_REFRESH_THRESHOLD:
                return self._session
            logger.info(f"Token expires in {remaining/60:.0f} min, refreshing...")

        self._session = self._get_or_capture_session()
        return self._session

    def _get_or_capture_session(self) -> OWASession:
        # 1. Try cached token (must have >30 min remaining)
        cached = self._load_cached_token()
        if cached:
            remaining = cached.expires_at - time.time()
            if remaining > TOKEN_REFRESH_THRESHOLD:
                logger.info(f"Using cached token ({remaining/60:.0f} min remaining).")
                return cached
            logger.info(f"Cached token expiring soon ({remaining/60:.0f} min), refreshing...")

        # 2. Try headless (silent, no UI) — works if browser session is still alive
        logger.info("Trying headless browser to refresh token silently...")
        session = self._capture_session(headless=True, timeout=20)
        if session:
            self._save_token(session)
            return session

        # 3. Fall back to visible browser for manual login
        logger.info("Session expired. Opening browser for login...")
        session = self._capture_session(headless=False, timeout=120)
        if session:
            self._save_token(session)
            return session

        raise RuntimeError("Failed to capture OWA token. Please try again.")

    def _capture_session(self, headless: bool, timeout: int) -> OWASession | None:
        """Open OWA, intercept API requests to find a working token."""
        captured: list[dict] = []

        with sync_playwright() as p:
            BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_STATE_DIR),
                headless=headless,
                channel="chrome",
            )

            page = context.pages[0] if context.pages else context.new_page()

            def handle_request(request):
                url = request.url
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and (
                    "outlook.office365.com/api/" in url
                    or "outlook.office365.com/owa/" in url
                    or "outlook.office.com/api/" in url
                    or "substrate.office.com" in url
                ):
                    captured.append({
                        "url": url,
                        "token": auth[7:],
                    })

            page.on("request", handle_request)

            if not headless:
                print("\n" + "=" * 60)
                print("浏览器已打开，请登录 Outlook Web。")
                print("登录完成后脚本会自动继续。")
                print("=" * 60 + "\n")

            page.goto(OWA_URL, wait_until="domcontentloaded")

            start = time.time()
            while (time.time() - start) < timeout:
                page.wait_for_timeout(2000)
                if captured:
                    logger.info(f"Captured {len(captured)} OWA API requests.")
                    break

            context.close()

        if not captured:
            return None

        return self._pick_best_session(captured)

    def _pick_best_session(self, captured: list[dict]) -> OWASession:
        """Pick the best captured request to derive API base and token."""
        for req in captured:
            if "outlook.office365.com/api/v2.0" in req["url"]:
                return self._make_session(req["token"])

        for req in captured:
            if "outlook.office365.com" in req["url"]:
                return self._make_session(req["token"])

        return self._make_session(captured[0]["token"])

    def _make_session(self, token: str) -> OWASession:
        exp = _get_token_expiry(token) or (time.time() + 3500)
        remaining = exp - time.time()
        logger.info(f"Token valid for {remaining/3600:.1f} hours (expires {time.strftime('%H:%M', time.localtime(exp))})")
        return OWASession(
            token=token,
            api_base="https://outlook.office365.com/api/v2.0",
            expires_at=exp,
            headers={"Authorization": f"Bearer {token}"},
        )

    # --- Token cache ---

    def _load_cached_token(self) -> OWASession | None:
        if not TOKEN_CACHE_FILE.exists():
            return None
        try:
            data = json.loads(TOKEN_CACHE_FILE.read_text())
            exp = data.get("expiry", 0)
            if exp > time.time():
                return OWASession(
                    token=data["token"],
                    api_base="https://outlook.office365.com/api/v2.0",
                    expires_at=exp,
                    headers={"Authorization": f"Bearer {data['token']}"},
                )
            logger.info("Cached token expired.")
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _save_token(self, session: OWASession):
        TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "token": session.token,
            "expiry": session.expires_at,
        }
        TOKEN_CACHE_FILE.write_text(json.dumps(data))
        logger.debug("Token cached to disk.")
