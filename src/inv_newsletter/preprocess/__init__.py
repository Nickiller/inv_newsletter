"""Email .md preprocessing & cleaning layer.

Single entry point: preprocess_email(content, sender_address) -> str

Stages:
1. Universal disclaimer / legal-footer / sales-contact stripping
2. Sender-specific reformatting (fomo-therapy today; JPM Tech Sketch planned)
"""

import re

from inv_newsletter.preprocess.disclaimer import strip_disclaimer
from inv_newsletter.preprocess.fomo_format import is_fomo_email, reformat_content
from inv_newsletter.preprocess.jpm_format import is_jpm_tech_sketch, reformat_jpm


def preprocess_email(content: str, sender_address: str) -> str:
    content = strip_disclaimer(content)
    subject = _extract_subject(content)
    if is_fomo_email(sender_address):
        content = reformat_content(content)
    elif is_jpm_tech_sketch(sender_address, subject):
        content = reformat_jpm(content)
    return content


def _extract_subject(content: str) -> str:
    m = re.search(r'^subject:\s*"(.*)"\s*$', content, flags=re.MULTILINE)
    return m.group(1) if m else ""


__all__ = [
    "preprocess_email",
    "strip_disclaimer",
    "is_fomo_email",
    "reformat_content",
    "is_jpm_tech_sketch",
    "reformat_jpm",
]
