"""Claude API-based email summarization with multimodal image support."""

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from openai import OpenAI

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
   - **禁止一句话条目**：每个 bullet point 必须包含"事实 + 背景/原因 + Implication"三要素中的至少两个。如果原文有足够信息，不要压缩成一句结论。
     - 差的例子：`对 RBLX、APP、U 负面，加剧 AI 颠覆熊市叙事`
     - 好的例子：`Rec Room 宣布关闭（单位经济始终未盈利 + VR 市场萎缩），紧随 Epic Games 上周裁员 1,000 人。Bernstein 认为连续关停加剧了游戏行业被 AI 颠覆的熊市叙事，对 RBLX、APP、U 构成负面情绪压力`

4. **来源标注与链接**：
   - 每条 bullet point 末尾**必须**标注原始出处链接，格式：`[来源名称](URL)`
   - 原文中几乎每条信息都附有 `[WSJ Tech](https://...)`, `[Bloomberg](https://...)` 等带链接的来源标注，请原样保留这些链接（包括重定向 URL，不要修改或简化）
   - 如果一条信息有多个来源链接，全部保留
   - 如果原文某条信息确实没有附链接，用 `*来源：{邮件标题简称} ({日期})*` 作为兜底
   - 示例：`微软将在泰国投资逾10亿美元建设云与AI基础设施 [WSJ Tech](https://23ed0f39...)`

5. **图表引用与分析**：
   - 每张图片都有一个唯一 ID（如 `IMG_01`），在发送时已标注
   - 当你认为某张图表对分析有价值时，**必须**用 markdown 图片语法嵌入：`![简短描述](IMG_01)`
   - 在图片嵌入之后，紧跟一段文字描述图表中的关键数据点（具体数字、百分比）和趋势
   - 不要嵌入 logo、签名、广告等无信息量的图片，只嵌入图表、数据表格、定价截图等有分析价值的图片
   - 示例：
     ```
     ![Anthropic 估值路径](IMG_05)
     📊 Coatue 预测 Anthropic 2030E 市值约 $1.995T（4.4x MOIC），2031E 收入 $200B，EBITDA $48B。
     ```

6. **催化剂日历**：在文末汇总"本周关注"事件（如有）。

## 输出格式

```markdown
# Daily Research Digest — {日期}

---

## 宏观与市场
...

## AI 模型与平台
### Ticker (公司名)
- 要点... *来源：XXX (MM/DD)*
...

---

> 基于 N 封研报邮件整理，按板块/Ticker 排序。
```
"""


def summarize_daily(
    data_dir: Path,
    output_dir: Path,
    target_date: str | None = None,
    model: str = "anthropic/claude-sonnet-4.6",
    max_tokens: int = 32000,
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

    # Load PDFs from data/pdfs/ directory
    pdfs_dir = data_dir.parent / "pdfs"
    pdfs = _load_pdfs(pdfs_dir, target_date)

    if not emails and not pdfs:
        raise RuntimeError(f"No emails or PDFs found for {target_date}")

    logger.info(f"Summarizing {len(emails)} emails + {len(pdfs)} PDFs for {target_date}")

    # Build API request
    content_blocks, image_map = _build_openai_content(emails, pdfs)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)

    logger.info(f"Calling API ({model}) via OpenAI-compatible endpoint (streaming)...")
    stream = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content_blocks},
        ],
    )

    chunks = []
    tokens_in = tokens_out = 0
    stop_reason = None
    for chunk in stream:
        if chunk.usage:
            tokens_in = chunk.usage.prompt_tokens
            tokens_out = chunk.usage.completion_tokens
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                chunks.append(delta.content)
            if chunk.choices[0].finish_reason:
                stop_reason = chunk.choices[0].finish_reason
    digest = "".join(chunks)
    logger.info(f"API response: {tokens_in} input tokens, {tokens_out} output tokens, stop_reason: {stop_reason}")

    # Write output
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{target_date}_daily_digest.md"

    # Replace IMG_XX references with actual image paths and copy images
    digest = _resolve_images(digest, image_map, output_dir, target_date)

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


def _load_pdfs(pdfs_dir: Path, target_date: str) -> list[dict]:
    """Load PDFs matching target date from pdfs directory, convert pages to images."""
    if not pdfs_dir.is_dir():
        return []

    # Match date patterns: YYYYMMDD or YYYY-MM-DD in filename
    date_compact = target_date.replace("-", "")  # "20260402"
    pdfs = []

    for pdf_path in sorted(pdfs_dir.glob("*.pdf")):
        name = pdf_path.stem
        if date_compact not in name and target_date not in name:
            continue

        logger.info(f"Loading PDF: {pdf_path.name}")
        pages = _pdf_to_images(pdf_path)
        if pages:
            pdfs.append({
                "path": pdf_path,
                "name": name,
                "pages": pages,  # list of (page_num, image_bytes) tuples
            })
        else:
            logger.warning(f"Failed to extract pages from {pdf_path.name}")

    return pdfs


def _pdf_to_images(pdf_path: Path, dpi: int = 120) -> list[tuple[int, bytes]]:
    """Convert PDF pages to JPEG images using pdftoppm. Returns [(page_num, jpeg_bytes)]."""
    if not shutil.which("pdftoppm"):
        logger.error("pdftoppm not found. Install poppler: brew install poppler")
        return []

    tmpdir = tempfile.mkdtemp(prefix="inv_pdf_")
    try:
        result = subprocess.run(
            ["pdftoppm", "-jpeg", "-jpegopt", "quality=65",
             "-r", str(dpi), str(pdf_path), f"{tmpdir}/page"],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"pdftoppm failed: {result.stderr.decode()}")
            return []

        pages = []
        total_bytes = 0
        for img_path in sorted(Path(tmpdir).glob("page-*.jpg")):
            page_num = int(img_path.stem.split("-")[-1])
            img_bytes = img_path.read_bytes()
            total_bytes += len(img_bytes)
            pages.append((page_num, img_bytes))

        logger.info(f"PDF converted: {len(pages)} pages, {total_bytes / 1024 / 1024:.1f}MB total")
        return pages
    except subprocess.TimeoutExpired:
        logger.error(f"pdftoppm timed out for {pdf_path.name}")
        return []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _resolve_images(
    digest: str, image_map: dict[str, Path], output_dir: Path, target_date: str,
) -> str:
    """Replace IMG_XX placeholders with relative paths and copy referenced images."""
    # Find all IMG_XX references in the digest
    referenced = set(re.findall(r"IMG_\d{2}", digest))
    if not referenced or not image_map:
        return digest

    # Create images subdirectory
    img_dir = output_dir / f"{target_date}_images"
    img_dir.mkdir(parents=True, exist_ok=True)

    for img_id in referenced:
        if img_id not in image_map:
            continue
        src = image_map[img_id]
        if not src.exists():
            continue
        dst = img_dir / f"{img_id}{src.suffix}"
        shutil.copy2(src, dst)
        # Replace IMG_XX with relative path from output_dir
        rel_path = f"{target_date}_images/{dst.name}"
        digest = digest.replace(f"]({img_id})", f"]({rel_path})")

    copied = sum(1 for i in referenced if i in image_map and image_map[i].exists())
    logger.info(f"Resolved {copied}/{len(referenced)} image references")
    return digest


def _build_openai_content(
    emails: list[dict], pdfs: list[dict] | None = None,
) -> tuple[list[dict], dict[str, Path]]:
    """Build multimodal content blocks for OpenAI-compatible API.

    Returns (content_blocks, image_map) where image_map is {IMG_ID: source_path}.
    """
    pdfs = pdfs or []
    blocks: list[dict] = []
    image_map: dict[str, Path] = {}  # IMG_01 -> /path/to/img.png
    img_counter = 0

    # Header
    parts = []
    if emails:
        parts.append(f"{len(emails)} 封投研邮件")
    if pdfs:
        parts.append(f"{len(pdfs)} 份 PDF 报告")
    blocks.append({
        "type": "text",
        "text": f"以下是 {'和'.join(parts)}，请按要求整理为每日摘要：\n",
    })

    for i, email in enumerate(emails, 1):
        fm = email["frontmatter"]
        subject = fm.get("subject", "Unknown")
        sender = fm.get("sender_name", "")
        addr = fm.get("sender_address", "")
        received = fm.get("received_at", "")

        # Email header + body
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

        # Attach key images (OpenAI vision format) with stable IDs
        for img in email["images"]:
            try:
                img_counter += 1
                img_id = f"IMG_{img_counter:02d}"
                img_data = base64.standard_b64encode(img["path"].read_bytes()).decode()
                image_map[img_id] = img["path"]
                blocks.append({
                    "type": "text",
                    "text": f"\n[图片 {img_id}: {img['name']} — 来自 {subject}]\n",
                })
                blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['media_type']};base64,{img_data}",
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to encode image {img['name']}: {e}")

    # PDF content (pages as images)
    for j, pdf in enumerate(pdfs, 1):
        blocks.append({
            "type": "text",
            "text": (
                f"\n{'='*60}\n"
                f"## PDF 报告 {j}/{len(pdfs)}\n"
                f"**来源**: {pdf['name']}\n"
                f"**页数**: {len(pdf['pages'])}\n"
                f"{'='*60}\n\n"
                f"以下是该 PDF 的每一页截图，请提取其中的所有投研信息：\n"
            ),
        })
        for page_num, img_bytes in pdf["pages"]:
            try:
                img_counter += 1
                img_id = f"IMG_{img_counter:02d}"
                img_data = base64.standard_b64encode(img_bytes).decode()
                # Save PDF page image to temp; will be copied later
                tmp_path = Path(tempfile.gettempdir()) / f"inv_pdf_{img_id}.jpg"
                tmp_path.write_bytes(img_bytes)
                image_map[img_id] = tmp_path
                blocks.append({
                    "type": "text",
                    "text": f"\n[图片 {img_id}: PDF 第 {page_num} 页 — {pdf['name']}]\n",
                })
                blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_data}",
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to encode PDF page {page_num}: {e}")

    return blocks, image_map


def _media_type(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
