"""JPM Tech Sketch email reflow.

JPM emails arrive as one giant markdown line (HTML was a single table cell).
This module:
1. Splits the body on inline ` --- ` separators (markdown HR converted from <hr>)
2. Drops table-pipe artifact sections (`|`, `| | `, etc.)
3. Lifts SHOUTY CAPS section titles into ## / ### headings
4. Splits inline ` - ` and ` * ` bullet markers onto real lines
"""

import re


def is_jpm_tech_sketch(sender_address: str, subject: str) -> bool:
    if not sender_address.lower().endswith("@jpmorgan.com"):
        return False
    subj = (subject or "").upper()
    return "JPM TECH SKETCH" in subj or "CHIPS FOR BREAKFAST" in subj


JPM_H2_TITLES = [
    "SCHILSKY'S SNAPSHOT",
    "NEWS – DESK COLOR – RESEARCH HIGHLIGHTS",
    "JPM TECH RESEARCH",
    "JPM TMT EVENT CALENDAR",
    "SCHILSKY'S SENTIMENT MONITORS",
    "TMT CORPORATE EVENT CALENDAR",
    "JPM EVENTS",
]

JPM_H3_SUBSECTIONS = [
    "INTERNET:",
    "SOFTWARE:",
    "MEDIA & TELECOM:",
    "HARDWARE:",
    "SEMIS:",
    "SEMICAP:",
    "DESK COLOR",
]


def _norm_apostrophe(s: str) -> str:
    return s.replace("’", "'").replace("‘", "'")


def reformat_jpm(content: str) -> str:
    """Reformat a JPM email markdown for readability. Returns original on failure."""
    m = re.match(r"^(---\n.*?\n---\n+)(# [^\n]+)\n+(.*)\Z", content, re.DOTALL)
    if not m:
        return content
    frontmatter, heading, body = m.group(1), m.group(2), m.group(3)

    reflowed_body = _reflow_body(body)
    if not reflowed_body.strip():
        return content
    return frontmatter + "\n" + heading + "\n\n" + reflowed_body.rstrip() + "\n"


def _reflow_body(body: str) -> str:
    sections = re.split(r"(?<=\s)---(?=\s)", body)

    output_blocks: list[str] = []
    for raw in sections:
        sec = _clean_section(raw)
        if not sec:
            continue
        block = _format_section(sec)
        if block.strip():
            output_blocks.append(block.strip())
    return "\n\n---\n\n".join(output_blocks)


def _clean_section(sec: str) -> str:
    """Strip leading table-pipe noise and condense whitespace.
    Returns "" if the section is pure noise."""
    sec = sec.strip()
    sec = re.sub(r"^[|\s​]+", "", sec)
    sec = re.sub(r"​", "", sec)
    sec = sec.strip()
    if len(sec) < 5:
        return ""
    if all(c in "| \t\n" for c in sec):
        return ""
    sec = re.sub(r"[ \t]+", " ", sec)
    return sec


def _format_section(sec: str) -> str:
    norm = _norm_apostrophe(sec).upper()

    for title in JPM_H2_TITLES:
        if norm.startswith(title.upper()):
            rest = sec[len(title):].lstrip(": \t")
            return f"## {title}\n\n" + _format_with_inline_h3(rest)

    return _format_with_inline_h3(sec)


def _format_with_inline_h3(text: str) -> str:
    """Format text body; if it starts with a known H3 subsection, lift that out."""
    text = text.strip()
    if not text:
        return ""
    upper = _norm_apostrophe(text).upper()
    for title in JPM_H3_SUBSECTIONS:
        if upper.startswith(title.upper()):
            rest = text[len(title):].lstrip(": \t")
            heading = f"### {title.rstrip(':')}"
            if not rest.strip():
                return heading + "\n"
            return heading + "\n\n" + _format_inline_bullets(rest)
    return _format_inline_bullets(text)


# Split on " - " preceded by a content character and followed by an uppercase / $ / digit
TOP_BULLET_SPLIT = re.compile(r"(?<=[\w.,;:!?\"'”’\)\]]) - (?=[A-Z\$\d])")
SUB_BULLET_SPLIT = re.compile(r"(?<=[\w.,;:!?\"'”’\)\]]) \* (?=[A-Z\$\d])")


def _format_inline_bullets(text: str) -> str:
    text = text.strip()
    if not text:
        return ""

    top_parts = TOP_BULLET_SPLIT.split(text)
    if len(top_parts) > 1:
        # Real top-level bullets via " - ". Within each, " * " becomes nested.
        lines = [top_parts[0].strip()]
        for p in top_parts[1:]:
            lines.append(f"- {_split_sub_bullets_nested(p.strip())}")
        return "\n\n".join(lines)

    # No " - " bullets. If " * " items exist, promote them to top-level "- ".
    star_parts = SUB_BULLET_SPLIT.split(text)
    if len(star_parts) > 1:
        items: list[str] = []
        first = star_parts[0].strip()
        if first.startswith("* "):
            items.append(f"- {first[2:].strip()}")
        elif first:
            items.append(first)  # preamble paragraph before first bullet
        for p in star_parts[1:]:
            items.append(f"- {p.strip()}")
        return "\n\n".join(items)

    return text


def _split_sub_bullets_nested(text: str) -> str:
    """Split " * " sub-bullets inside a top-level bullet (indented)."""
    parts = SUB_BULLET_SPLIT.split(text)
    if len(parts) == 1:
        return text
    out = [parts[0].strip()]
    for p in parts[1:]:
        out.append(f"  * {p.strip()}")
    return "\n".join(out)
