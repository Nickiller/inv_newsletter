"""Digest post-processing: canonical section/industry reordering, ticker-heading
classification, and the taxonomy drift audit (misclassified / unmapped tickers).

Operates purely on the rendered digest markdown + the taxonomy — no LLM calls.
summarizer.py re-exports _reorder_sections, _drift_audit, _write_drift_logs (used
in the main pipeline) and _reorder_industries_within_section (used by tests).
"""

import re
from pathlib import Path

from .taxonomy import Taxonomy, get_default_taxonomy

def _norm_section_title(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s).lower()


def _reorder_industries_within_section(
    section_body: str, sector_name: str, taxonomy: Taxonomy
) -> str:
    """Reorder ### industry headings within a ## sector per taxonomy.industry_order.

    Unknown industries (LLM-coined titles not in taxonomy) keep their relative
    order and are appended after the known ones.
    """
    industry_order = taxonomy.industry_order(sector_name)
    if not industry_order:
        return section_body

    lines = section_body.split("\n")
    h3_starts = [i for i, l in enumerate(lines) if l.startswith("### ")]
    if len(h3_starts) < 2:
        return section_body

    preamble = "\n".join(lines[: h3_starts[0]]).rstrip()

    chunks: list[tuple[str, str]] = []
    for idx, start in enumerate(h3_starts):
        end = h3_starts[idx + 1] if idx + 1 < len(h3_starts) else len(lines)
        title = lines[start][4:].strip()
        body = "\n".join(lines[start:end]).rstrip()
        chunks.append((title, body))

    canon_norm = [_norm_section_title(t) for t in industry_order]

    def rank(title: str) -> tuple[int, int]:
        norm = _norm_section_title(title)
        if norm in canon_norm:
            return (canon_norm.index(norm), 0)
        return (len(canon_norm), 0)  # unknown industries appended after known

    # stable sort preserves order among unknowns
    chunks.sort(key=lambda x: rank(x[0]))

    parts = [preamble] + [c[1] for c in chunks]
    return "\n\n".join(p for p in parts if p)


def _reorder_sections(digest: str, taxonomy: Taxonomy | None = None) -> str:
    """Reorder top-level ## sections + ### industries per taxonomy.

    Sections not in the canonical list are inserted between '软件与SaaS' and '其他'
    (preserves their relative order). Within each section, ### industry subheadings
    are reordered per taxonomy.industry_order(sector). Preamble (H1 + any
    pre-section text) is kept on top.
    """
    tax = taxonomy or get_default_taxonomy()
    sector_order = tax.sector_order()

    lines = digest.split("\n")
    section_starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if len(section_starts) < 2:
        return digest

    preamble = "\n".join(lines[: section_starts[0]]).rstrip()

    sections: list[tuple[str, str, str]] = []  # (raw_title, canonical_sector_or_None, body)
    for idx, start in enumerate(section_starts):
        end = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(lines)
        title = lines[start][3:].strip()
        body = "\n".join(lines[start:end]).rstrip()
        canonical = _match_canonical_sector(title, sector_order)
        if canonical:
            body = _reorder_industries_within_section(body, canonical, tax)
        sections.append((title, canonical, body))

    canon_norm = [_norm_section_title(t) for t in sector_order]
    unknown_anchor = canon_norm.index(_norm_section_title("其他")) if "其他" in sector_order else len(canon_norm)

    def rank(canonical: str | None, raw_title: str) -> tuple[int, int]:
        if canonical:
            return (canon_norm.index(_norm_section_title(canonical)), 0)
        return (unknown_anchor, -1)  # before "其他", after the previous known sector

    sections.sort(key=lambda x: rank(x[1], x[0]))

    parts = [preamble] + [s[2] for s in sections]
    return "\n\n".join(p for p in parts if p) + "\n"


def _match_canonical_sector(title: str, sector_order: list[str]) -> str | None:
    norm_title = _norm_section_title(title)
    for canonical in sector_order:
        if _norm_section_title(canonical) == norm_title:
            return canonical
    return None


# ── Drift audit ──────────────────────────────────────────────────────────


# Match the leading chunk of a #### / ### heading before " — " / " - " / " (" / EOL.
# Used to lift "NVDA" out of "NVDA (NVIDIA) — body" and "SK Hynix" out of "SK Hynix — body".
# Applied to both H4 (ticker headings) and H3 fallback (when LLM skipped H4 level).
_TICKER_HEADING_RE = re.compile(r"^#{3,4}\s+(.+?)(?:\s+[—–\-:]|\s+\(|$)", re.MULTILINE)

# A bare ticker-shaped token: 1-6 ASCII uppercase letters/digits. Used to detect
# headings worth flagging as 'unmapped' when they have no taxonomy match. Theme
# headings ("CPO 节奏前移", "Apple-Intel 协议") fail this and are skipped silently.
_TICKER_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")

# First leading ASCII uppercase token (e.g. "TSMC" out of "TSMC 与 COUPE 路线图").
_LEADING_ASCII_TICKER_RE = re.compile(r"^([A-Z][A-Za-z0-9]{0,7})\b")


def _classify_heading_candidate(
    heading_text: str, taxonomy: Taxonomy
) -> tuple[tuple[str, str, str] | None, str, bool]:
    """Try to classify the leading 'subject' of a #### heading.

    Returns (classification, candidate_text, is_ticker_shaped):
      - classification: (sector, industry, canonical_ticker) or None
      - candidate_text: best-guess subject pulled out of the heading
      - is_ticker_shaped: True if the candidate looks like a bare ticker token
        (worth flagging as 'unmapped' when taxonomy lookup fails)

    Theme headings ("CPO 节奏前移", "TSMC 与 COUPE / 先进封装路线图") that don't
    resolve to a ticker are returned with classification=None,
    is_ticker_shaped=False so the caller can skip them silently.
    """
    candidate = heading_text.strip()
    if not candidate:
        return None, "", False

    # 1. Try a full-string classify (handles "SK Hynix", "兆易创新", "Palo Alto Networks")
    result = taxonomy.classify(candidate)
    if result is not None:
        return result, candidate, True

    # 2. Try the first ASCII ticker token (handles "TSMC 与 COUPE 路线图" → TSMC)
    m = _LEADING_ASCII_TICKER_RE.match(candidate)
    if m:
        first_token = m.group(1)
        result = taxonomy.classify(first_token)
        if result is not None:
            return result, first_token, True

    # 3. No taxonomy hit. Only flag as 'unmapped' if the whole candidate
    #    looks like a bare ticker shape (uppercase, ≤6 chars, no spaces).
    is_ticker_shape = bool(_TICKER_SHAPE_RE.fullmatch(candidate))
    return None, candidate, is_ticker_shape


def _check_ticker_heading(
    line: str,
    current_sector: str,
    taxonomy: Taxonomy,
    misclassified: list[dict],
    unmapped: list[dict],
) -> None:
    """Run ticker drift checks against a #### / ### heading line.

    Appends to misclassified / unmapped in place. Theme headings without a
    ticker subject are skipped silently.
    """
    m = _TICKER_HEADING_RE.match(line)
    if not m:
        return
    result, candidate, is_ticker_shape = _classify_heading_candidate(m.group(1), taxonomy)
    if result is None:
        if is_ticker_shape:
            unmapped.append({
                "kind": "ticker",
                "ticker": candidate,
                "found_in": current_sector,
                "heading": line.strip(),
            })
        return
    accepted_sectors = {loc[0] for loc in taxonomy.accepted_locations(candidate)}
    if current_sector not in accepted_sectors:
        misclassified.append({
            "kind": "ticker",
            "ticker": candidate,
            "canonical_ticker": result[2],
            "found_in": current_sector,
            "expected": result[0],
            "heading": line.strip(),
        })


def _drift_audit(digest: str, taxonomy: Taxonomy | None = None) -> dict:
    """Detect misclassifications + unmapped tickers in #### and ### headings.

    Returns dict with:
      - misclassified: list of records; each record has ``kind`` ∈ {"ticker", "industry"}
        - ticker drift: {kind: "ticker", ticker, canonical_ticker, found_in, expected, heading}
        - industry drift: {kind: "industry", industry, found_in, expected, heading}
      - unmapped: list of {kind: "ticker", ticker, found_in, heading}

    Detection scope:
      - `#### TICKER` headings: classified as ticker drift if ticker is in
        taxonomy but not in any accepted (primary + also_in) sector.
      - `### industry` headings: if the heading text matches a known
        taxonomy industry, classified as industry drift when found in the
        wrong sector. Otherwise the H3 is treated as a possible ticker
        heading (catches cases where the LLM put `### CRCL` instead of
        `#### CRCL`).
      - Body-text cross-references (NVDA mentioned inside TSMC body) are
        NOT flagged.
      - Theme headings without a ticker / industry subject are skipped
        silently (e.g. `#### CPO 节奏前移`).
    """
    tax = taxonomy or get_default_taxonomy()
    misclassified: list[dict] = []
    unmapped: list[dict] = []

    lines = digest.split("\n")
    current_sector: str | None = None
    for line in lines:
        if line.startswith("## "):
            title = line[3:].strip()
            current_sector = _match_canonical_sector(title, tax.sector_order()) or title
            continue
        if current_sector is None:
            continue

        if line.startswith("#### "):
            _check_ticker_heading(line, current_sector, tax, misclassified, unmapped)
            continue

        if line.startswith("### "):
            heading_text = line[4:].strip()
            # First try as an industry name (allows minor punctuation differences).
            owner = tax.industry_to_sector(heading_text)
            if owner is not None:
                if owner != current_sector:
                    misclassified.append({
                        "kind": "industry",
                        "industry": heading_text,
                        "found_in": current_sector,
                        "expected": owner,
                        "heading": line.strip(),
                    })
                continue
            # Not a known industry → maybe LLM used ### where it should have
            # used #### for a single ticker (e.g. "### CRCL — ..."). Fall
            # through to ticker check.
            _check_ticker_heading(line, current_sector, tax, misclassified, unmapped)

    return {"misclassified": misclassified, "unmapped": unmapped}


def _drift_subject(item: dict) -> str:
    """Return the human-facing subject of a drift record (ticker symbol or industry name)."""
    if item.get("kind") == "industry":
        return item.get("industry", "?")
    return item.get("canonical_ticker") or item.get("ticker") or "?"


def _write_drift_logs(report: dict, target_date: str, logs_dir: Path) -> None:
    """Write drift + unmapped findings to logs/ for human review.

    File format is append-only newline-delimited records for easy `tail -f` review.
    Each drift record is prefixed with its ``kind`` (ticker | industry).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    if report["misclassified"]:
        with (logs_dir / "digest_drift.log").open("a", encoding="utf-8") as fp:
            for item in report["misclassified"]:
                kind = item.get("kind", "ticker")
                subject = _drift_subject(item)
                fp.write(
                    f"{target_date}\t{kind}\t{subject}\t"
                    f"found_in={item['found_in']}\texpected={item['expected']}\t"
                    f"heading={item['heading']}\n"
                )
    if report["unmapped"]:
        with (logs_dir / "unmapped_tickers.log").open("a", encoding="utf-8") as fp:
            for item in report["unmapped"]:
                fp.write(
                    f"{target_date}\t{item['ticker']}\tfound_in={item['found_in']}\t"
                    f"heading={item['heading']}\n"
                )

