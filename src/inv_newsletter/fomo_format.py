"""Reformat fomo-therapy email.md: strip table noise, split sections and bullets."""

import re

FOMO_SENDER = "zezhou@notifications.alphaholic.app"


def is_fomo_email(sender_address: str) -> bool:
    return sender_address.lower() == FOMO_SENDER


def _parse_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---\n"):
        return "", content
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return "", content
    return f"---\n{parts[1]}---\n", parts[2]


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _split_brief_updates(text: str) -> list[str]:
    """Items separated by `)<2+ spaces>` before next non-bracket text."""
    parts = re.split(r"\)\s{2,}(?=[^\[\s])", text)
    out = []
    for i, p in enumerate(parts):
        if i < len(parts) - 1:
            out.append(p + ")")
        else:
            out.append(p)
    return [_collapse_ws(p) for p in out if p.strip()]


def _split_bulleted(text: str) -> list[str]:
    """Split on isolated ` * ` bullet (avoid splitting inside `**Implication:**`)."""
    parts = re.split(r"(?<!\*)\* (?!\*)", text)
    return [_collapse_ws(p) for p in parts if p.strip()]


def _format_bulleted_item(item: str) -> list[str]:
    item = _collapse_ws(item)
    pieces = re.split(r"\*\*Implication:\*\*", item)
    body = pieces[0].strip()
    lines = [f"- {body}"]
    for impl in pieces[1:]:
        lines.append(f"  - **Implication:** {impl.strip()}")
    return lines


def reformat_content(content: str) -> str:
    """Reformat a fomo-therapy email.md string. Returns original if structure unrecognized."""
    frontmatter, body = _parse_frontmatter(content)
    if not frontmatter:
        return content

    body_lines = body.split("\n")
    heading_idx = None
    for i, line in enumerate(body_lines):
        if line.startswith("# FOMO Therapy"):
            heading_idx = i
            break
    if heading_idx is None:
        return content

    preview_parts = []
    big_idx = None
    for i in range(heading_idx + 1, len(body_lines)):
        line = body_lines[i]
        if line.lstrip().startswith("|"):
            big_idx = i
            break
        if line.strip():
            preview_parts.append(line.strip())
    if big_idx is None:
        return content

    preview = _collapse_ws(" ".join(preview_parts))
    big_line = body_lines[big_idx]

    bu = re.search(r"Brief Updates\s+", big_line)
    kh = re.search(r"Key Highlights\s+", big_line)
    af = re.search(r"Additional Focus\s+", big_line)
    help_m = re.search(r"Help shape the newsletter", big_line)

    if not bu or not kh:
        return content

    bu_text = big_line[bu.end():kh.start()].strip()
    if af:
        kh_text = big_line[kh.end():af.start()].strip()
        af_text = big_line[af.end():help_m.start() if help_m else len(big_line)].strip()
    else:
        kh_text = big_line[kh.end():help_m.start() if help_m else len(big_line)].strip()
        af_text = ""

    bu_items = _split_brief_updates(bu_text)
    kh_items = _split_bulleted(kh_text)
    af_items = _split_bulleted(af_text) if af_text else []

    out = [frontmatter.rstrip(), "", body_lines[heading_idx], ""]
    if preview:
        out.extend([preview, ""])

    out.extend(["## Brief Updates", ""])
    for it in bu_items:
        out.append(f"- {it}")
    out.append("")

    out.extend(["## Key Highlights", ""])
    for it in kh_items:
        out.extend(_format_bulleted_item(it))
        out.append("")

    if af_items:
        out.extend(["## Additional Focus", ""])
        for it in af_items:
            out.extend(_format_bulleted_item(it))
            out.append("")

    return "\n".join(out).rstrip() + "\n"
