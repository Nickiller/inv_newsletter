#!/usr/bin/env python3
"""Section-aware digest quality judge.

Splits a digest by `## ` headings, scores each section against the user-authored
rubric via Sonnet (with structured tool_use output), and renders a section × axis
heatmap report.

Usage:
    uv run scripts/judge_digest.py --digest output/daily/2026-05-13_daily_digest.md
    uv run scripts/judge_digest.py --digest <path> --rubric evals/rubric.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

SECTOR_NAMES = {
    "AI 模型与平台",
    "宏观与市场",
    "半导体与硬件",
    "互联网与数字广告",
    "软件与SaaS",
    "网络安全",
    "其他",
}
CATALYST_PREFIXES = ("本周关注", "催化剂")

JUDGE_MODEL_DEFAULT = "claude-sonnet-4-6"

TLDR_AXES = ["A1", "A2", "A3", "A4"]
SECTOR_AXES = ["B1", "B2", "B3", "B4", "B5"]

JUDGE_INSTRUCTIONS = (
    "You are a quality judge for an investment-research daily digest. "
    "You will receive (a) a rubric authored by the human reader and (b) one section "
    "of a digest. Apply the rubric verbatim — do not invent new criteria or relax "
    "thresholds. For each axis, output an integer score 1-5 and a 1-2 sentence "
    "rationale that cites specific lines or phrases from the section. Use the "
    "score_section tool to return your scores."
)


def split_sections(digest_text: str) -> list[tuple[str, str]]:
    """Split digest into [(title, body), ...] by H2 (`## `) headers."""
    pattern = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(digest_text))
    sections = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(digest_text)
        body = digest_text[body_start:body_end].strip()
        sections.append((title, body))
    return sections


def classify_section(title: str) -> str:
    """Return one of: 'tldr', 'sector', 'catalyst', 'skip'."""
    if any(title.startswith(p) for p in CATALYST_PREFIXES):
        return "catalyst"
    # Sector match: title starts with or equals any known sector name (allow
    # decorative suffixes like '## 半导体与硬件 (Memory cycle)' someday)
    for s in SECTOR_NAMES:
        if title == s or title.startswith(s + " ") or title.startswith(s + "—"):
            return "sector"
    return "tldr"


def extract_rubric_part(rubric_text: str, part_letter: str) -> str:
    """Extract `## Part {letter} — ...` block up to the next Part header or `---`."""
    next_letter = chr(ord(part_letter) + 1)
    pattern = re.compile(
        rf"^## Part {part_letter}\b.+?(?=^## Part [{next_letter}-Z]|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(rubric_text)
    return m.group(0).strip() if m else ""


def warn_if_rubric_unfilled(rubric_text: str) -> None:
    placeholder_count = rubric_text.count("_填这里_")
    if placeholder_count:
        print(
            f"⚠️  Warning: rubric has {placeholder_count} unfilled `_填这里_` placeholders. "
            "Judge will run but quality of scores will be poor until you fill these in.",
            file=sys.stderr,
        )


def build_tool_schema(axes: list[str]) -> dict:
    return {
        "name": "score_section",
        "description": "Score one digest section across the rubric axes",
        "input_schema": {
            "type": "object",
            "properties": {
                axis: {
                    "type": "object",
                    "properties": {
                        "score": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "description": f"Integer score 1-5 for axis {axis}",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "1-2 sentences citing specific lines/phrases from the section",
                        },
                    },
                    "required": ["score", "rationale"],
                }
                for axis in axes
            },
            "required": axes,
        },
    }


def judge_section(
    client: anthropic.Anthropic,
    model: str,
    section_title: str,
    section_body: str,
    rubric_part: str,
    axes: list[str],
) -> dict:
    tool = build_tool_schema(axes)
    system = [
        {"type": "text", "text": JUDGE_INSTRUCTIONS},
        {
            "type": "text",
            "text": f"# Rubric (verbatim, apply as-is)\n\n{rubric_part}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    user_text = f"# Section to score: `{section_title}`\n\n{section_body}"
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": "score_section"},
        messages=[{"role": "user", "content": user_text}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "score_section":
            result = block.input
            # Sonnet sometimes double-serializes nested dicts as JSON strings inside
            # tool_use. Detect and parse.
            for axis in axes:
                v = result.get(axis)
                if isinstance(v, str):
                    try:
                        result[axis] = json.loads(v.strip())
                    except json.JSONDecodeError:
                        pass
            # Validate structure: each axis must be {"score": int, "rationale": str}
            bad_axes = []
            for axis in axes:
                v = result.get(axis)
                if not isinstance(v, dict) or "score" not in v or "rationale" not in v:
                    bad_axes.append((axis, type(v).__name__))
            if bad_axes:
                raise RuntimeError(
                    f"Tool output malformed for `{section_title}`. "
                    f"Bad axes (type): {bad_axes}"
                )
            return result
    raise RuntimeError(f"Judge did not call tool for section `{section_title}`")


def render_report(scores: dict, output_path: Path, digest_path: Path) -> None:
    lines = [
        f"# Judge Report — {digest_path.name}",
        "",
        f"_Scored {len(scores)} section(s) against rubric._",
        "",
        "## Heatmap (section × axis)",
        "",
    ]
    all_axes: list[str] = []
    for sect_scores in scores.values():
        for axis in sect_scores:
            if axis not in all_axes:
                all_axes.append(axis)
    lines.append("| Section | " + " | ".join(all_axes) + " |")
    lines.append("| --- | " + " | ".join(["---"] * len(all_axes)) + " |")
    for section_title, sect_scores in scores.items():
        row = [f"`{section_title}`"]
        for axis in all_axes:
            if axis in sect_scores:
                s = sect_scores[axis]["score"]
                emoji = "🟢" if s >= 4 else ("🟡" if s == 3 else "🔴")
                row.append(f"{emoji} {s}")
            else:
                row.append("—")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Per-section detail")
    for section_title, sect_scores in scores.items():
        lines.append(f"\n### `{section_title}`")
        for axis, data in sect_scores.items():
            lines.append(f"- **{axis}** ({data['score']}/5): {data['rationale']}")

    flat = [
        (sect, axis, data["score"])
        for sect, sect_scores in scores.items()
        for axis, data in sect_scores.items()
    ]
    flat.sort(key=lambda x: x[2])
    lines.append("\n## Weakest 5 cells")
    for sect, axis, score in flat[:5]:
        lines.append(f"- `{sect}` × **{axis}** = {score}/5")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--digest", required=True, type=Path, help="Path to digest .md")
    parser.add_argument(
        "--rubric",
        type=Path,
        default=Path("evals/rubric.md"),
        help="Path to user-authored rubric.md (default: evals/rubric.md)",
    )
    parser.add_argument(
        "--model",
        default=JUDGE_MODEL_DEFAULT,
        help=f"Judge model (default: {JUDGE_MODEL_DEFAULT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report path; default: <digest>.judge.md alongside the digest",
    )
    args = parser.parse_args()

    if not args.digest.exists():
        print(f"Error: digest not found: {args.digest}", file=sys.stderr)
        sys.exit(1)
    if not args.rubric.exists():
        print(f"Error: rubric not found: {args.rubric}", file=sys.stderr)
        sys.exit(1)

    digest_text = args.digest.read_text(encoding="utf-8")
    rubric_text = args.rubric.read_text(encoding="utf-8")
    warn_if_rubric_unfilled(rubric_text)

    tldr_rubric = extract_rubric_part(rubric_text, "A")
    sector_rubric = extract_rubric_part(rubric_text, "B")
    if not tldr_rubric or not sector_rubric:
        print(
            "Error: could not extract Part A or Part B from rubric. "
            "Make sure headers are exactly `## Part A` and `## Part B`.",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    sections = split_sections(digest_text)
    if not sections:
        print(f"Error: no `## ` sections found in {args.digest}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(sections)} section(s) in {args.digest.name}")
    scores: dict[str, dict] = {}
    for title, body in sections:
        kind = classify_section(title)
        if kind == "catalyst":
            print(f"  [skip catalyst] `{title}`")
            continue
        rubric_part = tldr_rubric if kind == "tldr" else sector_rubric
        axes = TLDR_AXES if kind == "tldr" else SECTOR_AXES
        print(f"  [{kind:6s}] `{title}` ({len(body):>5} chars)...", end=" ", flush=True)
        try:
            result = judge_section(client, args.model, title, body, rubric_part, axes)
            scores[title] = result
            avg = sum(d["score"] for d in result.values()) / len(result)
            print(f"avg {avg:.1f}/5")
        except Exception as e:
            print(f"ERROR: {e}")
            continue

    if not scores:
        print("No sections scored successfully.", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or args.digest.with_suffix(".judge.md")
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    render_report(scores, output_path, args.digest)
    print(f"\nReport: {output_path}")
    print(f"Raw:    {json_path}")


if __name__ == "__main__":
    main()
