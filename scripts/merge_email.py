#!/usr/bin/env python3
"""Incremental merge: fold a single new email into an existing digest.

Cheap alternative to full re-summarize when one email was missed by the
fetch pass. Calls Opus once with the existing digest + new email and asks
for an integrated digest. Preserves existing content verbatim where the
new email is silent.

Usage:
    uv run scripts/merge_email.py \
        --digest output/daily/2026-05-21_daily_digest.md \
        --email  data/mail/2026-05-21/1205-jeffereis-tech-.../email.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

load_dotenv(override=True)

MERGE_SYSTEM_PROMPT = """你是一位资深投研分析师助手。你的任务是把一封新邮件的内容**增量整合**进一份**已生成的 daily digest**。

**硬性规则**：

1. **保留现有 digest 的所有内容**——除非新邮件直接补充/更正某个具体段落（如同一 ticker 新数据点、新引用、新观点），否则**一字不改**。
2. **新邮件的内容按 ticker / 主题归到已有的对应 section**（半导体 / 软件 / 互联网 / AI 等）。如果某个 ticker 已经独立成段（`#### TICKER`），在该段内追加新邮件的视角；如果是新 ticker，按现有 section 的 ticker 排序插入合理位置。
3. **不要新增 section**——所有内容必须落进现有的 `## ` 一级标题下。如果新邮件提到 `## 宏观与市场` 类主题但 digest 当前没有这个 section，也不要新建（按 ticker 归类到对应 sector）。
4. **TL;DR / 今日要点段落不要动**——它由独立 stage-2 pass 生成；merge 不触发 TL;DR 重写。
5. **本周关注段落仅在新邮件提供具体催化剂事件时追加 bullet**，不要重写整段。
6. **风格与现有 digest 保持一致**：headline 句式 (`#### TICKER — {数字/价格} + {核心论点}`)、段落 flow、bullet + 粗体 inline、链接紧跟内容、中英混排习惯，全部沿用现有 digest 的写法。
7. **引用规则**：新邮件里出现的链接必须保留（特别是 Jefferies 卖方研报链接）。锚文本可用"Jefferies — Brent"或"Jefferies 研报"之类有信息量的描述。

**输出格式**：返回**完整的** merged digest（从 `# Daily Research Digest — ...` 开始到结尾，包括所有未变的 section）。**不要**返回 diff、不要返回 "已整合" 之类的说明文字，**直接返回整篇 markdown**。
"""


def _price_estimate(model: str, in_tok: int, out_tok: int) -> float:
    pricing = {
        "opus":   (15.00, 75.00),
        "sonnet": (3.00, 15.00),
        "haiku":  (1.00,  5.00),
    }
    for tier, (i, o) in pricing.items():
        if tier in model.lower():
            return in_tok / 1_000_000 * i + out_tok / 1_000_000 * o
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", required=True, type=Path, help="existing digest markdown")
    ap.add_argument("--email", required=True, type=Path, help="new email markdown to merge in")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--max-tokens", type=int, default=20000)
    ap.add_argument("--dry-run", action="store_true", help="print merged content, don't overwrite")
    args = ap.parse_args()

    digest_text = args.digest.read_text(encoding="utf-8")
    email_text = args.email.read_text(encoding="utf-8")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    base_url = os.environ.get("ANTHROPIC_BASE_URL") or None
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    user_msg = (
        "<existing_digest>\n"
        f"{digest_text}\n"
        "</existing_digest>\n\n"
        "<new_email>\n"
        f"{email_text}\n"
        "</new_email>\n\n"
        "请把 <new_email> 的内容增量整合进 <existing_digest>，返回完整 merged digest。"
    )

    print(f"→ merging {args.email.name} into {args.digest.name}")
    print(f"  digest: {len(digest_text):,} chars, email: {len(email_text):,} chars")
    print(f"  model: {args.model}, max_tokens: {args.max_tokens}")

    resp = client.messages.create(
        model=args.model,
        max_tokens=args.max_tokens,
        system=MERGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    merged = "".join(b.text for b in resp.content if hasattr(b, "text"))
    in_tok = resp.usage.input_tokens
    out_tok = resp.usage.output_tokens
    cost = _price_estimate(args.model, in_tok, out_tok)

    print(f"\n  tokens: in {in_tok:,} / out {out_tok:,} → est. ${cost:.4f}")
    print(f"  merged length: {len(merged):,} chars (was {len(digest_text):,}, Δ {len(merged) - len(digest_text):+,})")

    if args.dry_run:
        print("\n--- merged (dry-run, not written) ---")
        print(merged)
        return

    # Backup original, then overwrite
    backup = args.digest.with_suffix(args.digest.suffix + ".bak")
    backup.write_text(digest_text, encoding="utf-8")
    args.digest.write_text(merged, encoding="utf-8")
    print(f"\n  ✓ backup: {backup}")
    print(f"  ✓ updated: {args.digest}")


if __name__ == "__main__":
    main()
