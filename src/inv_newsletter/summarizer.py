"""Claude API-based email summarization with multimodal image support."""

import base64
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import anthropic
import yaml

logger = logging.getLogger(__name__)

MIN_IMAGE_SIZE = 50 * 1024  # 50KB — skip logos/banners (提高阈值减少图片数量)
MAX_IMAGES_PER_EMAIL = 3  # 每封邮件最多 3 张图（降低以减轻中转站负担）
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

SYSTEM_PROMPT = """\
你是一位资深投研分析师助手。请将以下多封投研邮件整理为结构化的每日摘要。

## 输出要求

1. **板块排序**：按以下顺序组织内容：
   - 宏观与市场
   - AI 模型与平台
   - 半导体与硬件
   - 互联网与数字广告
   - 软件与SaaS
   - 网络安全
   - 其他

2. **Ticker 归类**：同一板块内按公司/Ticker 归类，合并多封邮件中对同一 Ticker 的分析。用 `### TICKER (公司名)` 作为小标题。如果某板块没有明确 Ticker，可用子主题分类（如"地缘政治与能源"、"市场情绪"）。

3. **中文详细输出**：
   - 保留关键数据（价格目标、估值倍数、增长率、市场份额、具体数字、百分比等）
   - 保留分析师观点、投资逻辑和业务细节
   - 每个要点用 bullet point
   - 不要过度压缩信息，保持原文的信息密度

4. **来源标注与链接**：
   - **原文中出现的所有链接都必须保留**，无论是主流媒体（WSJ、Bloomberg、CNBC、Reuters 等）还是社区来源（TMTB Chat、Tae Kim、Semianalysis、FundaAI、Substack 等），格式：`[来源名](完整URL)` 紧跟在相关内容后
   - 同一条内容若有多个来源链接，全部并排列出
   - **如果已有具体链接，不需要再附加 `*来源：XXX (MM/DD)*`**；只有在没有任何具体链接时，才在末尾加 `*来源：{邮件标题简称} ({日期})*`
   - 示例（有链接）：`OpenAI 完成融资 [Tae Kim](https://x.com/...) [The Information](https://theinformation.com/...)`
   - 示例（无链接）：`分析师认为软件名义将滞后 *来源：Jefferies (04/01)*`

5. **图表分析**：如果邮件附带了图表图片，请描述图表中的关键数据点（具体数字、百分比）和趋势（上升/下降/对比），并标注 `📊 [图表]`。

6. **催化剂日历**：在文末汇总"本周关注"事件（如有）。

## 输出格式

```markdown
# Daily Research Digest — {日期}

> 基于 N 封研报邮件整理，按板块/Ticker 排序。

---

## 宏观与市场
...

## AI 模型与平台
### Ticker (公司名)
- 要点... *来源：XXX (MM/DD)*
...
```
"""


def summarize_daily(
    data_dir: Path,
    output_dir: Path,
    target_date: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 8192,
) -> Path:
    """Load emails for a date, call Claude API, write digest. Returns output path."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to .env or environment.")

    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    # Determine date
    if target_date is None:
        # Find the most recent date directory
        date_dirs = sorted(data_dir.glob("20*-*-*"), reverse=True)
        if not date_dirs:
            raise RuntimeError(f"No email data found in {data_dir}")
        target_date = date_dirs[0].name
    else:
        if not (data_dir / target_date).exists():
            raise RuntimeError(f"No data for date {target_date} in {data_dir}")

    date_dir = data_dir / target_date
    emails = _load_emails(date_dir)
    if not emails:
        raise RuntimeError(f"No emails found for {target_date}")

    logger.info(f"Summarizing {len(emails)} emails for {target_date}")

    # Build API request
    content_blocks = _build_content_blocks(emails)
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    logger.info(f"Calling Claude API ({model})...")
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content_blocks}],
    )

    digest = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    stop_reason = response.stop_reason
    logger.info(f"API response: {tokens_in} input tokens, {tokens_out} output tokens, stop_reason: {stop_reason}")

    # Write output
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{target_date}_daily_digest.md"
    output_path.write_text(digest, encoding="utf-8")

    logger.info(f"Digest written to {output_path}")
    return output_path


def _load_emails(date_dir: Path) -> list[dict]:
    """Load all email.md files from a date directory."""
    emails = []
    for email_md in sorted(date_dir.glob("*/email.md")):
        email_dir = email_md.parent
        try:
            raw = email_md.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(raw)
            images = _select_key_images(email_dir, frontmatter.get("images", []))
            emails.append({
                "dir": email_dir,
                "frontmatter": frontmatter,
                "body": body,
                "images": images,
            })
        except Exception as e:
            logger.warning(f"Failed to load {email_md}: {e}")
    return emails


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


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
        selected.append({
            "path": path,
            "name": name,
            "size": size,
            "media_type": _media_type(ext),
        })
        if len(selected) >= MAX_IMAGES_PER_EMAIL:
            break
    return selected


def _build_content_blocks(emails: list[dict]) -> list[dict]:
    """Build multimodal content blocks for Claude API."""
    blocks: list[dict] = []

    blocks.append({
        "type": "text",
        "text": f"以下是 {len(emails)} 封投研邮件，请按要求整理为每日摘要：\n",
    })

    for i, email in enumerate(emails, 1):
        fm = email["frontmatter"]
        subject = fm.get("subject", "Unknown")
        sender = fm.get("sender_name", "")
        addr = fm.get("sender_address", "")
        received = fm.get("received_at", "")

        # Email header
        blocks.append({
            "type": "text",
            "text": (
                f"\n{'='*60}\n"
                f"## 邮件 {i}/{len(emails)}\n"
                f"**标题**: {subject}\n"
                f"**发件人**: {sender} <{addr}>\n"
                f"**时间**: {received}\n"
                f"{'='*60}\n\n"
                f"{email['body']}\n"
            ),
        })

        # Attach key images
        for img in email["images"]:
            try:
                img_data = base64.standard_b64encode(img["path"].read_bytes()).decode()
                blocks.append({
                    "type": "text",
                    "text": f"\n[附图: {img['name']} — 来自 {subject}]\n",
                })
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img_data,
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to encode image {img['name']}: {e}")

    return blocks


def _media_type(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
