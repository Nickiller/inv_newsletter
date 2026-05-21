"""Render a daily digest markdown to a polished single-file HTML artifact.

Phase 1 (MVP): deterministic md → HTML with embedded CSS, sticky sidebar TOC,
ticker badges, callout boxes, click-to-zoom images. No LLM in this path.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import markdown

from .taxonomy import get_default_taxonomy

logger = logging.getLogger(__name__)


# Strip the optional YAML-like frontmatter that some digests carry; the digest
# pipeline currently does not emit any, but be defensive.
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _build_ticker_regex() -> re.Pattern[str]:
    """Compile a single alternation over all known English tickers from the taxonomy.

    Chinese aliases are skipped — they read as company names in prose and
    look odd in monospace badges. We only badge uppercase Latin symbols.
    """
    tax = get_default_taxonomy()
    symbols: set[str] = set()
    for sector in tax.sectors:
        for industry in sector.industries:
            for entry in industry.tickers:
                if re.match(r"^[A-Z][A-Z0-9.\-]{1,8}$", entry.ticker):
                    symbols.add(entry.ticker)
                for alias in entry.aliases:
                    if re.match(r"^[A-Z][A-Z0-9.\-]{1,8}$", alias):
                        symbols.add(alias)
    # Sort by length desc so longer symbols match first (e.g. AMZN before AMZ)
    alternation = "|".join(re.escape(s) for s in sorted(symbols, key=len, reverse=True))
    # Word boundary before; after must not be a letter/digit/dot/dash (so "MSFT/AAPL" still matches both).
    return re.compile(rf"(?<![A-Za-z0-9.\-])({alternation})(?![A-Za-z0-9])")


_TICKER_RE = _build_ticker_regex()
_LINK_TAG_RE = re.compile(r"<a\b[^>]*>.*?</a>", re.DOTALL)
_CODE_TAG_RE = re.compile(r"<code>.*?</code>", re.DOTALL)


def _badge_tickers(html: str) -> str:
    """Wrap recognized tickers in <span class='ticker'>…</span>.

    Operates on rendered HTML. To avoid badging tickers that already live
    inside <a> links or <code> blocks (rare but possible), we mask those
    sections out, do the substitution, then restore them.
    """
    placeholders: list[str] = []

    def stash(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00PH{len(placeholders) - 1}\x00"

    masked = _LINK_TAG_RE.sub(stash, html)
    masked = _CODE_TAG_RE.sub(stash, masked)

    def wrap(m: re.Match) -> str:
        return f"<span class='ticker'>{m.group(1)}</span>"

    badged = _TICKER_RE.sub(wrap, masked)

    # Restore placeholders.
    def restore(m: re.Match) -> str:
        return placeholders[int(m.group(1))]

    return re.sub(r"\x00PH(\d+)\x00", restore, badged)


_CSS = """
:root {
  --bg: #fafaf7;
  --fg: #1a1a1a;
  --muted: #6b6b6b;
  --accent: #c1462b;
  --border: #e5e3dc;
  --sidebar-bg: #f3f1ea;
  --callout-bg: #fffaf0;
  --callout-border: #e0c97f;
  --ticker-bg: #1a1a1a;
  --ticker-fg: #ffffff;
  --link: #2c5282;
  --code-bg: #f3f1ea;
  --max-w: 760px;
  --sidebar-w: 240px;
}

* { box-sizing: border-box; }

html { scroll-behavior: smooth; }

body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: "Source Han Serif SC", "Songti SC", "Noto Serif CJK SC",
               Georgia, "Times New Roman", serif;
  font-size: 16px;
  line-height: 1.75;
}

.layout {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  max-width: calc(var(--sidebar-w) + var(--max-w) + 80px);
  margin: 0 auto;
}

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { display: none; }
}

.sidebar {
  padding: 32px 16px 32px 24px;
  border-right: 1px solid var(--border);
  background: var(--sidebar-bg);
  position: sticky;
  top: 0;
  align-self: start;
  max-height: 100vh;
  overflow-y: auto;
  font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
  font-size: 13px;
  line-height: 1.55;
}

.sidebar .sb-title {
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 12px;
}

.sidebar ol {
  list-style: none;
  padding: 0;
  margin: 0 0 18px;
}

.sidebar li { margin: 4px 0; }

.sidebar a {
  color: var(--fg);
  text-decoration: none;
  display: block;
  padding: 2px 0;
}

.sidebar a:hover { color: var(--accent); }

.sidebar .sb-section { font-weight: 500; }
.sidebar .sb-sub { padding-left: 12px; color: var(--muted); font-size: 12px; }

main {
  padding: 32px 40px 80px;
  max-width: var(--max-w);
}

header.doc-header {
  border-bottom: 2px solid var(--fg);
  padding-bottom: 16px;
  margin-bottom: 28px;
}

.doc-header .eyebrow {
  font-family: -apple-system, "Helvetica Neue", sans-serif;
  font-size: 11px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 6px;
}

.doc-header h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.01em;
}

.doc-header .meta {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
  font-family: -apple-system, "Helvetica Neue", sans-serif;
}

h2 {
  font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
  font-size: 22px;
  font-weight: 700;
  margin: 48px 0 18px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  letter-spacing: -0.005em;
}

h2:first-of-type { border-top: none; padding-top: 0; }

h3 {
  font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
  font-size: 16px;
  font-weight: 600;
  margin: 28px 0 12px;
  color: var(--muted);
  text-transform: none;
  letter-spacing: 0.01em;
}

h4 {
  font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
  font-size: 18px;
  font-weight: 600;
  margin: 28px 0 10px;
  line-height: 1.4;
  color: var(--fg);
  border-left: 3px solid var(--accent);
  padding-left: 12px;
}

p {
  margin: 0 0 14px;
  line-height: 1.8;
}

ul, ol { margin: 0 0 16px; padding-left: 22px; }
li { margin: 6px 0; line-height: 1.7; }
li > ul, li > ol { margin: 6px 0; }

strong { font-weight: 600; color: var(--fg); }

a {
  color: var(--link);
  text-decoration: none;
  border-bottom: 1px solid rgba(44, 82, 130, 0.25);
}
a:hover { border-bottom-color: var(--link); }

.ticker {
  font-family: "SF Mono", Monaco, "Courier New", monospace;
  font-size: 0.88em;
  background: var(--ticker-bg);
  color: var(--ticker-fg);
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 0.02em;
  font-weight: 500;
  white-space: nowrap;
}

code {
  font-family: "SF Mono", Monaco, "Courier New", monospace;
  font-size: 0.88em;
  background: var(--code-bg);
  padding: 1px 5px;
  border-radius: 3px;
}

img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 16px auto;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: zoom-in;
  transition: transform 0.15s ease;
}

img:hover { transform: scale(1.01); }

/* TL;DR section gets a distinct background */
section.tldr {
  background: var(--callout-bg);
  border: 1px solid var(--callout-border);
  border-radius: 6px;
  padding: 20px 28px;
  margin-bottom: 32px;
}

section.tldr h2 {
  border-top: none;
  margin-top: 0;
  padding-top: 0;
  font-size: 18px;
}

section.tldr > ul { padding-left: 18px; }
section.tldr > ul > li { margin: 12px 0; }

/* Source footer */
.source-footer {
  margin-top: 64px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  font-family: -apple-system, "Helvetica Neue", sans-serif;
  font-size: 12px;
  color: var(--muted);
}

/* Lightbox */
.lightbox-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: none;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  cursor: zoom-out;
}

.lightbox-overlay.active { display: flex; }

.lightbox-overlay img {
  max-width: 92vw;
  max-height: 92vh;
  border: none;
  border-radius: 6px;
  cursor: zoom-out;
}
"""


_JS = """
(function() {
  // Click-to-zoom for body images.
  const overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  const big = document.createElement('img');
  overlay.appendChild(big);
  document.body.appendChild(overlay);
  overlay.addEventListener('click', () => overlay.classList.remove('active'));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') overlay.classList.remove('active');
  });
  document.querySelectorAll('main img').forEach((img) => {
    img.addEventListener('click', () => {
      big.src = img.src;
      overlay.classList.add('active');
    });
  });
})();
"""


def _cjk_slugify(text: str, sep: str = "-") -> str:
    """Slugify that keeps Chinese characters intact.

    python-markdown's default slugifier drops non-ASCII, mapping Chinese
    headings to empty strings (which then get auto-numbered `_1`, `_2`, …).
    This version preserves CJK so anchors stay readable.
    """
    s = re.sub(r"[\s]+", sep, text.strip().lower())
    s = re.sub(r"[^\w一-鿿\-]", "", s)
    s = s.strip(sep)
    return s or "section"


def _build_toc(md_text: str) -> str:
    """Build sidebar TOC HTML from H2 / H3 headings in the markdown source.

    Uses the same slug scheme as the python-markdown toc extension (we pass
    `_cjk_slugify` to both) so sidebar links and heading anchors line up.
    """
    items: list[tuple[int, str, str]] = []  # (level, text, slug)
    seen_slugs: dict[str, int] = {}

    def slug_with_dedup(text: str) -> str:
        base = _cjk_slugify(text)
        n = seen_slugs.get(base, 0)
        seen_slugs[base] = n + 1
        return base if n == 0 else f"{base}_{n}"

    for line in md_text.splitlines():
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2)
        items.append((level, text, slug_with_dedup(text)))

    if not items:
        return ""

    parts = ['<p class="sb-title">目录</p>', "<ol>"]
    for level, text, slug in items:
        cls = "sb-section" if level == 2 else "sb-sub"
        parts.append(f'<li class="{cls}"><a href="#{slug}">{text}</a></li>')
    parts.append("</ol>")
    return "\n".join(parts)


def _wrap_tldr_section(html: str) -> str:
    """Wrap the `今日要点` H2 + immediate body in a callout <section>.

    The python-markdown output is a flat list of siblings; we find the H2 whose
    text is `今日要点` and wrap it together with following nodes until the next H2.
    """
    pattern = re.compile(
        r'(<h2[^>]*>今日要点</h2>)(.*?)(?=<h2|\Z)',
        re.DOTALL,
    )
    return pattern.sub(
        lambda m: f'<section class="tldr">{m.group(1)}{m.group(2)}</section>',
        html,
        count=1,
    )


def _rewrite_image_paths(html: str, md_path: Path, target_date: str) -> str:
    """Resolve relative image paths against the .md file's directory.

    The digest markdown references images as `YYYY-MM-DD/IMG_XX.png`, which
    is relative to `output/daily/`. For the HTML to render correctly when
    opened directly, we keep those paths as-is — the HTML sits next to the .md.
    """
    # No-op for MVP — the HTML lands in the same dir as the .md so relative
    # paths work. Reserved for future absolute-URL hosting.
    return html


def render_digest_html(md_path: Path, html_path: Path | None = None) -> Path:
    """Convert a digest markdown file to a single-file HTML artifact.

    Args:
        md_path: path to YYYY-MM-DD_daily_digest.md
        html_path: optional override; defaults to md_path with .html suffix.

    Returns the written HTML path.
    """
    md_path = Path(md_path)
    if html_path is None:
        html_path = md_path.with_suffix(".html")
    else:
        html_path = Path(html_path)

    md_text = md_path.read_text(encoding="utf-8")
    md_text = _FRONTMATTER_RE.sub("", md_text)

    # Extract date from filename (YYYY-MM-DD_daily_digest.md)
    m = re.match(r"(\d{4}-\d{2}-\d{2})_", md_path.name)
    target_date = m.group(1) if m else ""

    body_html = markdown.markdown(
        md_text,
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={
            "toc": {
                "toc_depth": "2-4",
                "anchorlink": False,
                "slugify": lambda text, sep: _cjk_slugify(text, sep),
            }
        },
    )
    body_html = _wrap_tldr_section(body_html)
    body_html = _badge_tickers(body_html)
    body_html = _rewrite_image_paths(body_html, md_path, target_date)

    toc_html = _build_toc(md_text)

    title = f"投研日报 · {target_date}" if target_date else "投研日报"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">{toc_html}</aside>
<main>
<header class="doc-header">
<p class="eyebrow">Daily Investment Digest</p>
<h1>{title}</h1>
<p class="meta">投研邮件 + 久谦专家纪要 · 由 Claude 综合整理</p>
</header>
{body_html}
<footer class="source-footer">
本页面由 inv_newsletter HTML renderer 生成 · {target_date}
</footer>
</main>
</div>
<script>{_JS}</script>
</body>
</html>
"""

    html_path.write_text(html, encoding="utf-8")
    logger.info(f"Rendered HTML digest: {html_path}")
    return html_path


def main() -> None:
    """CLI entry: `python -m inv_newsletter.html_renderer <md_path>`."""
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Render daily digest .md → polished single-file HTML")
    parser.add_argument("md_path", type=Path, help="path to YYYY-MM-DD_daily_digest.md")
    parser.add_argument("--out", type=Path, default=None, help="output HTML path (default: <md>.html)")
    args = parser.parse_args()
    out = render_digest_html(args.md_path, args.out)
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
