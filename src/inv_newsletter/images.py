"""Image handling for the daily digest: selection, Haiku captioning (with an
on-disk cache), label/caption overlap scoring, reference validation, and
embedding referenced images into the published digest.

`_build_content_blocks` (the multimodal payload assembly) intentionally stays
in summarizer.py — it is mostly email/meritco *text* with images interleaved,
i.e. core orchestration rather than image handling.
"""

import base64
import json
import logging
import re
import shutil
import time
from pathlib import Path

import anthropic

from .cost import _record_usage, _run_usage
from .timing import get_timer

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

MIN_IMAGE_SIZE = 35 * 1024  # 35KB — skip logos/banners but keep small data charts
MAX_IMAGE_SIZE = 1_500_000  # 1.5MB — skip oversize screenshots that break proxy streaming
MAX_IMAGES_PER_EMAIL = 5  # 每封邮件最多 5 张图（图表多的邮件如 JPM Sentiment Monitor 需要更多额度）
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

CAPTION_MODEL = "claude-haiku-4-5-20251001"
CAPTION_CACHE_FILE = Path("data/.image_caption_cache.json")
CAPTION_PROMPT = (_PROMPTS_DIR / "image_caption.md").read_text(encoding="utf-8").strip()


def _tokenize_caption(text: str) -> set[str]:
    """Tokenize a caption into chars (CJK) + lowercase ASCII words for overlap scoring."""
    text = (text or "").lower()
    # ASCII words: keep them whole
    words = set(re.findall(r"[a-z0-9]+", text))
    # CJK chars: each char is a token (skip ASCII chars / punctuation already covered)
    chars = {c for c in text if "一" <= c <= "鿿"}
    return words | chars


def _caption_overlap(label: str, inv_caption: str) -> float:
    """Directional overlap: fraction of label's tokens that appear in inventory caption.

    Asymmetric on purpose — the LLM's user-facing label is usually short ("AI 安全威胁"),
    while the inventory caption is verbose ("截图，AI 安全威胁应对策略与平台厂商竞争..."），
    so symmetric Jaccard would unfairly penalize legitimate matches. We accept any
    label whose tokens are mostly contained in the inventory caption.
    """
    a, b = _tokenize_caption(label), _tokenize_caption(inv_caption)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


CAPTION_MATCH_THRESHOLD = 0.3  # min directional overlap (label-tokens-in-inventory)


def _validate_image_refs(digest: str, img_caption: dict[str, str]) -> str:
    """Drop reused / out-of-range / caption-mismatched IMG_XX references.

    Strategy:
      1. Find every `![label](IMG_NN)` reference (with optional trailing 📊 description line)
      2. Group by IMG_NN
      3. For each group: pick the occurrence whose label has highest overlap with
         img_caption[IMG_NN]; drop all others. If even the best is below threshold,
         drop all occurrences.
      4. Out-of-range IDs (not in img_caption): drop all occurrences.

    Removed lines are replaced with empty strings (the surrounding text stands).
    """
    pattern = re.compile(r"!\[([^\]]*)\]\((IMG_\d+)\)[ \t]*\n?(?:📊[^\n]*\n?)?")

    # Collect all matches with positions
    matches = list(pattern.finditer(digest))
    if not matches:
        return digest

    # Group by IMG_NN
    by_id: dict[str, list[tuple[re.Match, float]]] = {}
    for m in matches:
        img_id = m.group(2)
        label = m.group(1)
        score = _caption_overlap(label, img_caption.get(img_id, ""))
        by_id.setdefault(img_id, []).append((m, score))

    # Decide which match position to keep (set of (start, end))
    keep_spans: set[tuple[int, int]] = set()
    drop_reasons: list[str] = []
    for img_id, items in by_id.items():
        if img_id not in img_caption:
            drop_reasons.append(f"  - {img_id}: out-of-range (not in inventory), dropping {len(items)} ref(s)")
            continue
        items.sort(key=lambda t: t[1], reverse=True)
        best_match, best_score = items[0]
        if best_score < CAPTION_MATCH_THRESHOLD:
            drop_reasons.append(
                f"  - {img_id}: best label overlap {best_score:.2f} < threshold "
                f"(inv: \"{img_caption[img_id]}\"), dropping all {len(items)} ref(s)"
            )
            continue
        keep_spans.add((best_match.start(), best_match.end()))
        if len(items) > 1:
            drop_reasons.append(
                f"  - {img_id}: kept best (overlap {best_score:.2f}), dropped {len(items)-1} duplicate(s)"
            )

    # Rebuild digest: drop matches not in keep_spans
    drop_count = 0
    out_parts: list[str] = []
    cursor = 0
    for m in matches:
        span = (m.start(), m.end())
        out_parts.append(digest[cursor:m.start()])
        if span in keep_spans:
            out_parts.append(m.group(0))
        else:
            drop_count += 1
        cursor = m.end()
    out_parts.append(digest[cursor:])

    if drop_count:
        logger.info(f"Image-ref validator dropped {drop_count} bad reference(s):")
        for line in drop_reasons:
            logger.info(line)
    return "".join(out_parts)


def _embed_images(digest: str, img_map: dict[str, Path], img_dir: Path, date_str: str) -> str:
    """Copy images referenced as IMG_XX into img_dir and rewrite markdown paths."""
    for img_id, src_path in img_map.items():
        if img_id not in digest:
            continue
        img_dir.mkdir(parents=True, exist_ok=True)
        ext = src_path.suffix.lower()
        dest_name = f"{img_id}{ext}"
        dest_path = img_dir / dest_name
        shutil.copy2(src_path, dest_path)
        # Use relative path from the .md file: {date}/IMG_XX.ext
        digest = digest.replace(img_id, f"{date_str}/{dest_name}")
        logger.debug(f"Copied image {img_id} → {date_str}/{dest_name}")
    return digest


def _load_caption_cache() -> dict[str, str]:
    if not CAPTION_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CAPTION_CACHE_FILE.read_text())
    except Exception as e:
        logger.warning(f"Caption cache unreadable, starting fresh: {e}")
        return {}


def _save_caption_cache(cache: dict[str, str]) -> None:
    CAPTION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CAPTION_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _caption_one_image(client: anthropic.Anthropic, img_path: Path, media_type: str) -> str:
    img_data = base64.standard_b64encode(img_path.read_bytes()).decode()
    resp = client.messages.create(
        model=CAPTION_MODEL,
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_data},
                },
                {"type": "text", "text": CAPTION_PROMPT},
            ],
        }],
    )
    _record_usage(CAPTION_MODEL, resp.usage)
    return resp.content[0].text.strip().replace("\n", " ")


def _caption_all_images(client: anthropic.Anthropic, emails: list[dict]) -> dict[str, str]:
    """Caption every selected image. Returns {path_str: caption}, cached on disk."""
    cache = _load_caption_cache()
    new_count = 0
    usage_start = len(_run_usage)
    t0 = time.perf_counter()
    for email in emails:
        for img in email["images"]:
            key = str(img["path"])
            if key in cache:
                continue
            try:
                cache[key] = _caption_one_image(client, img["path"], img["media_type"])
                new_count += 1
                logger.debug(f"Captioned {img['path'].name}: {cache[key]}")
            except Exception as e:
                logger.warning(f"Caption failed for {img['path']}: {e}")
                cache[key] = ""  # mark attempted; empty caption falls back to subject
    duration = time.perf_counter() - t0
    if new_count:
        _save_caption_cache(cache)
        logger.info(f"Captioned {new_count} new image(s) with {CAPTION_MODEL}")
        new_entries = _run_usage[usage_start:]
        get_timer().record_llm_call(
            "haiku_caption",
            model=CAPTION_MODEL,
            duration_sec=duration,
            tokens_in=sum(e["input_tokens"] for e in new_entries),
            tokens_out=sum(e["output_tokens"] for e in new_entries),
            calls=new_count,
        )
    return cache


def _select_key_images(email_dir: Path, image_names: list[str]) -> list[dict]:
    """Filter images to keep only charts/data (skip logos/banners)."""
    selected = []
    for name in image_names:
        path = email_dir / name
        if not path.exists():
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        size = path.stat().st_size
        if size < MIN_IMAGE_SIZE:
            continue
        if size > MAX_IMAGE_SIZE:
            logger.info(f"Skipping oversize image {name} ({size/1e6:.1f}MB > {MAX_IMAGE_SIZE/1e6:.1f}MB)")
            continue
        selected.append({
            "path": path,
            "name": name,
            "size": size,
            "media_type": _media_type(ext),
        })
        if len(selected) >= MAX_IMAGES_PER_EMAIL:
            break
    return selected


def _media_type(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
