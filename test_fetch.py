"""Quick test: open OWA via browser, capture token, fetch emails."""

import logging
from inv_newsletter.auth import OutlookBrowser
from inv_newsletter.outlook import OutlookClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# 1. Open browser and capture OWA session
browser = OutlookBrowser()

# 2. Fetch recent emails (last 24h, no filters)
client = OutlookClient(browser)
emails = client.fetch_emails(hours_back=24)

# 3. Print results
print(f"\n{'='*60}")
print(f"Found {len(emails)} emails in the last 24 hours:")
print(f"{'='*60}")
for i, email in enumerate(emails, 1):
    print(f"\n[{i}] {email.subject}")
    print(f"    From: {email.sender_name} <{email.sender_address}>")
    print(f"    Time: {email.received_at.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"    Preview: {email.body_preview[:100]}...")
