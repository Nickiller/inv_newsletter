"""Stage-2 TL;DR generator.

Two-stage architecture: stage 1 (summarizer.py) generates sectors only; stage 2
(this module) takes the rendered draft and extracts a `## 今日要点` block.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import anthropic

TLDR_PROMPT_PATH = Path(__file__).parent / "prompts" / "tldr.md"
TLDR_HEADER_RE = re.compile(r"^## 今日要点\s*\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
TLDR_DEFAULT_MODEL = "claude-opus-4-7"


def strip_existing_tldr(digest_md: str) -> str:
    """Remove any existing `## 今日要点` section (until next `## `).

    Used both defensively before stage-2 (in case stage-1 generated one despite
    prompt edits) and idempotently when re-running stage-2 on an already-augmented
    digest.
    """
    return TLDR_HEADER_RE.sub("", digest_md, count=1).lstrip()


def prepend_tldr(digest_md: str, tldr_md: str) -> str:
    """Insert `## 今日要点` block after the H1 line, before the first `## sector`."""
    cleaned = strip_existing_tldr(digest_md)
    lines = cleaned.split("\n")
    insert_idx = 0
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            insert_idx = i
            break
    new_lines = lines[:insert_idx] + [tldr_md.strip(), ""] + lines[insert_idx:]
    return "\n".join(new_lines)


def generate_tldr(
    digest_body: str,
    model: str = TLDR_DEFAULT_MODEL,
    prompt_text: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> tuple[str, dict]:
    """Call Claude with tldr prompt + digest body. Returns (tldr_md, usage_dict).

    usage_dict has: input_tokens, output_tokens, duration_sec, stop_reason.
    """
    if prompt_text is None:
        prompt_text = TLDR_PROMPT_PATH.read_text(encoding="utf-8")
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    user_msg = (
        f"<digest>\n{digest_body.strip()}\n</digest>\n\n"
        "上方 <digest> 是一份当日已完成的投研 digest。请按 system prompt 抽取 `## 今日要点` 速读块。"
    )

    t0 = time.perf_counter()
    chunks: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=4000,
        system=[{"type": "text", "text": prompt_text}],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for txt in stream.text_stream:
            chunks.append(txt)
        final = stream.get_final_message()
    duration = time.perf_counter() - t0

    text = "".join(chunks).strip()
    text = re.sub(r"^```(?:markdown)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    usage = {
        "input_tokens": getattr(final.usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(final.usage, "output_tokens", 0) or 0,
        "duration_sec": duration,
        "stop_reason": final.stop_reason,
    }
    return text, usage
