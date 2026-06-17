"""De-AI-style review pass (去 AI 味儿审查).

Takes a finished digest and rewrites stiff / mechanical / "AI-flavored" Chinese
prose into natural, professional buy-side language — WITHOUT touching any fact,
number, ticker, link, image ref, heading, or structure.

Mirrors the tldr.py shape: a single post-processing LLM call over the rendered
digest. A deterministic safety gate (URL + IMG_XX set comparison) guards every
run: if the model dropped or altered any link/image, we roll back to the
original digest rather than ship a corrupted one — code answers what code can
verify, the model only does the judgment call (prose).
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import anthropic

REVIEW_PROMPT_PATH = Path(__file__).parent / "prompts" / "reviewer.md"
REVIEW_DEFAULT_MODEL = "claude-sonnet-4-6"

_URL_RE = re.compile(r"https?://[^\s\)\]]+")
_IMG_RE = re.compile(r"IMG_\d+")
_FENCE_OPEN_RE = re.compile(r"^```(?:markdown)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")


def link_img_signature(md: str) -> tuple[list[str], list[str]]:
    """Deterministic fingerprint of a digest: ordered URLs + IMG_XX refs.

    Two digests with identical signatures preserve every link and image ref in
    the same order — the only invariant the review pass must never break.
    """
    return _URL_RE.findall(md), _IMG_RE.findall(md)


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = _FENCE_OPEN_RE.sub("", text)
    text = _FENCE_CLOSE_RE.sub("", text)
    return text.strip()


def review_digest(
    digest_md: str,
    model: str = REVIEW_DEFAULT_MODEL,
    prompt_text: str | None = None,
    client: anthropic.Anthropic | None = None,
    max_tokens: int = 32000,
) -> tuple[str, dict]:
    """Call Claude with the reviewer prompt + digest. Returns (reviewed_md, usage).

    usage has: input_tokens, output_tokens, duration_sec, stop_reason.
    Raw model output only — NOT safety-checked. Use naturalize() for the guarded
    version that rolls back on link/image drift.
    """
    if prompt_text is None:
        prompt_text = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    user_msg = (
        f"<digest>\n{digest_md.strip()}\n</digest>\n\n"
        "上方 <digest> 是一份已定稿的投研 digest。请按 system prompt 做去 AI 味儿的文风审查，"
        "直接输出审查后的整份 digest。"
    )

    t0 = time.perf_counter()
    chunks: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": prompt_text, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for txt in stream.text_stream:
            chunks.append(txt)
        final = stream.get_final_message()
    duration = time.perf_counter() - t0

    reviewed = _strip_fence("".join(chunks))
    usage = {
        "input_tokens": getattr(final.usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(final.usage, "output_tokens", 0) or 0,
        "duration_sec": duration,
        "stop_reason": final.stop_reason,
    }
    return reviewed, usage


def naturalize(
    digest_md: str,
    model: str = REVIEW_DEFAULT_MODEL,
    prompt_text: str | None = None,
    client: anthropic.Anthropic | None = None,
    logger=None,
) -> tuple[str, dict]:
    """Guarded review: run review_digest, verify the safety gate, roll back on drift.

    Returns (out_md, usage). usage gains:
      - safe (bool): did the gate pass
      - used_review (bool): is out_md the reviewed version (True) or original (False)
      - gate (str): human-readable gate result

    The contract: this function can never return a digest with a different set of
    links or image refs than the input. Worst case it returns the input unchanged.
    """
    def _log(msg: str) -> None:
        if logger is not None:
            logger(msg)

    src_urls, src_imgs = link_img_signature(digest_md)
    reviewed, usage = review_digest(digest_md, model, prompt_text, client)
    out_urls, out_imgs = link_img_signature(reviewed)

    safe = (src_urls == out_urls) and (src_imgs == out_imgs)
    if safe:
        usage.update(safe=True, used_review=True,
                     gate=f"PASS ({len(src_urls)} urls / {len(src_imgs)} imgs preserved)")
        return reviewed, usage

    # Drift detected → roll back. Surface, don't silently ship.
    detail = (f"urls {len(src_urls)}→{len(out_urls)}, imgs {len(src_imgs)}→{len(out_imgs)}")
    _log(f"⚠️ reviewer safety gate FAILED ({detail}) — rolling back to un-reviewed digest")
    usage.update(safe=False, used_review=False, gate=f"FAIL ({detail}) — rolled back")
    return digest_md, usage
