"""Strip disclaimer / legal-footer / sales-contact noise from email markdown.

Two-pass:
1. Find the earliest "disclaimer cutoff" phrase (Disclaimers:, FOR INSTITUTIONAL...,
   Link to Disclaimer:, The information provided herein..., © 20XX ... All rights...).
   Truncate from there, guarded so we don't gut emails where a disclaimer-shaped
   sentence appears in the middle of real content.
2. Walk backward from the cut, eating signature paragraphs (phone, email,
   bank LLC, job title, brand logo) plus one "name-like" line above the block.
"""

import re

CUTOFF_PATTERNS = [
    r"\bDisclaimers?:",                                            # JPM
    r"Sales\s*&\s*Trading\s+Disclaimer:?",                         # JPM secondary
    r"FOR INSTITUTIONAL & PROFESSIONAL CLIENTS ONLY",              # JPM backup
    r"Tech Sector Specialists:",                                   # JPM contact block
    r"The information provided herein was prepared by",            # Bernstein
    r"This communication is not a research report",                # Bernstein backup
    r"Link to Disclaimer:",                                        # Jefferies (forward)
    r"\*?This material is a product of [^\n]+? Sales and Trading", # Jefferies italic legal
    r"^Disclaimer:\s*\[?http",                                     # Jefferies direct
    r"This material has been prepared by [^\n]+? Sales and Trading",  # generic
    r"©\s*20\d{2}[^\n]+?All rights reserved",                      # generic copyright
    r"IMPORTANT\s+(DISCLOSURES?|DISCLAIMERS?)\b",                  # generic
]

MIN_KEPT_CHARS = 200
MAX_CUT_FRACTION = 0.70
MIN_CUT_CHARS = 100

# --- Signature / logo trimming ---

BANK_BRANDS = (
    r"Jefferies|JPMorgan|JPM|Bernstein|BernsteinSG|Morgan Stanley|"
    r"Goldman Sachs|Goldman|Citigroup|Citi|Wolfe Research|Wolfe"
)

# Length-independent: brand-logo image lines often carry long URLs but are pure footer.
BRAND_LOGO_PATTERN = re.compile(
    rf"!\[[^\]]*({BANK_BRANDS})[^\]]*\]",
    re.IGNORECASE,
)

STRONG_SIG_PATTERNS = [
    # Phone
    r"^\*?\*?(Cell|Phone|Tel|Mobile|Direct|Office|Fax)\s*[:+]\s*[+\d]",
    r"^\*?\*?(T|M|O|D|F)\s+\+\d",
    r"^\+\d[\d \-()]{5,}",
    # Email-only paragraph
    r"^\[?[\w.+\-]+@[\w.\-]+\]?$",
    r"^\[[\w.+\-]+@[\w.\-]+\]\(mailto:",
    # Job titles
    r"\b(Equities Trading|Equity Sales|Sector Specialist|Specialist Sales|"
    r"Sales Trader|Managing Director|Vice President|Director,|Analyst,\s+Asia|"
    r"TMT Specialist Sales|Hardware\s*&\s*Semis|US TMT|EU TMT|Asia Tech\s*&\s*Semis)\b",
    # Company suffix
    rf"\b({BANK_BRANDS})\s+(LLC|Inc\.?|Limited|Securities|Partners)\s*$",
    # Standalone bank-name line
    rf"^\*?\*?({BANK_BRANDS})\*?\*?$",
]

WEAK_NAME_PATTERN = re.compile(
    r"^\*?\*?[A-Z][\w'.\- ]{1,40}\*?\*?$"  # short bold or plain "Name Name" line
)


def _classify_para(text: str) -> str:
    """Return 'strong' | 'weak' | 'content'.

    strong = definitely part of signature/logo footer (phone, email, LLC, job title, brand logo)
    weak   = name-like line (acceptable as sig only if preceded by a strong line below it)
    content = real content; stop trimming
    """
    if not text:
        return "strong"  # blank line — keep walking

    # Structural content markers first (cheap, definitive)
    if text.startswith(("|", "* ", "- ", "#", "> ")):
        return "content"

    # Brand logo: catch before length check (URLs make these lines long)
    if BRAND_LOGO_PATTERN.search(text):
        return "strong"

    if len(text) > 150:
        return "content"

    for pat in STRONG_SIG_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE):
            return "strong"

    if WEAK_NAME_PATTERN.fullmatch(text):
        return "weak"
    return "content"


def _trim_signature_above(content: str, cut: int) -> int:
    """Walk backward from `cut` swallowing signature/logo paragraphs.

    Accept a paragraph as sig if it's strong, or if it's weak AND the paragraph
    immediately following it (closer to `cut`) was strong (i.e., a "name" line
    sitting on top of phone/email/job-title block).
    """
    pos = cut
    while pos > 0 and content[pos - 1] in " \t\n":
        pos -= 1

    last_was_strong = False
    while True:
        prev_break = content.rfind("\n\n", 0, pos)
        if prev_break == -1:
            break
        para = content[prev_break + 2 : pos].strip()
        cls = _classify_para(para)
        if cls == "strong":
            pos = prev_break
            last_was_strong = True
        elif cls == "weak" and last_was_strong:
            pos = prev_break
            last_was_strong = False
        else:
            break
    return pos


# --- Public entry ---

def strip_disclaimer(content: str) -> str:
    cleaned, _ = _strip_disclaimer_debug(content)
    return cleaned


def _strip_disclaimer_debug(content: str) -> tuple[str, dict]:
    total = len(content)
    if total < MIN_KEPT_CHARS + MIN_CUT_CHARS:
        return content, {"applied": False, "reason": "too_short", "total": total}

    candidates: list[tuple[int, str, str]] = []
    for pattern in CUTOFF_PATTERNS:
        for m in re.finditer(pattern, content, flags=re.IGNORECASE | re.MULTILINE):
            cut_index = m.start()
            removed = total - cut_index
            if cut_index < MIN_KEPT_CHARS:
                continue
            if removed < MIN_CUT_CHARS:
                continue
            if removed / total > MAX_CUT_FRACTION:
                continue
            candidates.append((cut_index, m.group(0)[:60], pattern))

    if not candidates:
        return content, {"applied": False, "reason": "no_safe_match", "total": total}

    candidates.sort(key=lambda x: x[0])
    raw_cut, marker, pattern = candidates[0]
    final_cut = _trim_signature_above(content, raw_cut)
    cleaned = content[:final_cut].rstrip() + "\n"
    return cleaned, {
        "applied": True,
        "marker": marker,
        "pattern": pattern,
        "raw_cut": raw_cut,
        "final_cut": final_cut,
        "sig_trim_chars": raw_cut - final_cut,
        "removed_chars": total - final_cut,
        "kept_chars": final_cut,
        "removed_fraction": round((total - final_cut) / total, 3),
        "total": total,
    }
