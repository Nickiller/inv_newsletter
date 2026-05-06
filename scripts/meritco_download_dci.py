"""Download the 7 selected DCI minutes as markdown into data/meritco_dci/.

Uses the existing meritco.py pipeline (HTML → markdown via html_to_markdown,
filename via Haiku-generated topic) but writes to a separate directory and
prepends the original forum URL to each file.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import (  # noqa: E402
    _get_token,
    _post_signed,
    API_BASE,
    BASE_URL,
    html_to_markdown,
    _make_filename,
    _escape_yaml,
)


IDS = [3125, 3076, 3044]  # weekly reports — companion MD to the PDFs

OUT_DIR = Path("data/meritco_dci")


def fetch_detail(token: str, forum_id: int) -> dict | None:
    body = {"platform": "RESEARCH_PC"}
    my_input = token + str(forum_id)
    forum_input = token + "  " + str(forum_id)
    url = f"{API_BASE}/forum/select/id?forumId={forum_id}"
    resp = _post_signed(url, token, body, my_input, forum_input)
    if resp.get("code") != 200:
        print(f"  [{forum_id}] API error: {resp.get('message')}")
        return None
    return resp.get("result") or None


def article_url(forum_id: int) -> str:
    """Original article URL on Meritco web SPA.

    Verified via login redirect: site routes to /report/auth?forumId={id}
    when accessed unauthenticated, confirming this is the entry path.
    """
    return f"{BASE_URL}/report/auth?forumId={forum_id}"


def save_markdown(item: dict) -> Path:
    forum_id = item["id"]
    meeting_time = item.get("meetingTime") or ""
    target_date = meeting_time[:10] if meeting_time else datetime.now().strftime("%Y-%m-%d")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    filename = _make_filename(item, target_date)
    out_path = OUT_DIR / filename

    title = item.get("title", "")
    expert = item.get("expertInformation") or ""
    summary = item.get("summary") or ""
    targets = item.get("relatedTargets") or []
    author = item.get("author") or ""
    industry = item.get("industry") or ""
    content_html = item.get("content") or ""

    body_md = html_to_markdown(content_html)
    url = article_url(forum_id)

    frontmatter = (
        "---\n"
        f"id: \"meritco-{forum_id}\"\n"
        f"subject: \"{_escape_yaml(title)}\"\n"
        f"sender_name: \"久谦论坛 ({expert})\"\n"
        f"sender_address: \"meritco-forum@meritco-group.com\"\n"
        f"received_at: \"{meeting_time}\"\n"
        f"fetched_at: \"{datetime.now().isoformat()}\"\n"
        f"images: []\n"
        f"source: \"meritco\"\n"
        f"source_url: \"{url}\"\n"
        f"tickers: {json.dumps(targets, ensure_ascii=False)}\n"
        f"industry: \"{industry}\"\n"
        "---\n\n"
    )

    header = f"# {title}\n\n"
    header += f"**原文链接**: <{url}>\n\n"
    header += f"**专家**: {expert} | **行业**: {industry} | **分析师**: {author}\n"
    if targets:
        header += f"**相关标的**: {', '.join(targets)}\n"
    header += f"**会议时间**: {meeting_time}\n\n"
    if summary:
        header += f"> **摘要**: {summary}\n\n"
    header += "---\n\n"

    out_path.write_text(frontmatter + header + body_md, encoding="utf-8")
    return out_path


def main():
    token = _get_token()
    print(f"Downloading {len(IDS)} DCI minutes to {OUT_DIR}/\n")

    saved = []
    for fid in IDS:
        print(f"[{fid}] fetching detail...", end=" ", flush=True)
        try:
            item = fetch_detail(token, fid)
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        if not item:
            print("no result")
            continue
        if not item.get("content"):
            print("EMPTY content (auth/permission issue?)")
            continue
        path = save_markdown(item)
        saved.append(path)
        print(f"saved → {path.name}")

    print(f"\nDone. {len(saved)}/{len(IDS)} files written:")
    for p in saved:
        size_kb = p.stat().st_size / 1024
        print(f"  {p}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
