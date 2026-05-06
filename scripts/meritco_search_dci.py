"""Search Meritco forum for DCI (Data Center Interconnection) related minutes/research.

Date range: 2026-03-01 ~ 2026-05-31
Tickers of interest: NOK (Nokia), GLW (Corning)

This script ONLY searches and prints candidates. No files are downloaded.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import (  # noqa: E402
    _get_token,
    _post_signed,
    API_BASE,
)

# Keywords to probe — covering the topic from multiple angles
KEYWORDS = [
    "DCI",
    "数据中心互联",
    "数据中心互连",
    "Nokia",
    "诺基亚",
    "Corning",
    "康宁",
    "光模块",
    "光通信",
    "硅光",
]

DATE_START = "2026-03-01 00:00:00"
DATE_END = "2026-05-31 23:59:59"
TARGET_TICKERS = {"NOK", "GLW"}


def search(token: str, keyword: str, page: int = 1, page_size: int = 50) -> dict:
    """Hit /forum/select/list with a keyword filter."""
    body = {
        "forumId": None,
        "page": page,
        "pageSize": page_size,
        "module": "CLASSIC_ALL_SEARCH",
        "contentTag": "",
        "publishTime": "",
        "codeIndustryId": "",
        "totalPage": "5",
        "sortColumn": "articleDate",
        "source": "",
        "reportTag": "全部标签",
        "platformArr": [
            "专业内容-纪要-国内市场-专家访谈",
            "专业内容-纪要-国内市场-业绩交流",
            "专业内容-纪要-国内市场-券商路演",
            "专业内容-纪要-海外市场",
            "专业内容-研报-国内市场",
            "专业内容-研报-海外市场",
            "专业内容-其他报告",
        ],
        "outCat1": "",
        "orgNameList": [],
        "outCat2": "",
        "keyword": keyword,
        "type": int(__import__("os").environ.get("MERITCO_TYPE", "2")),
        "industryList": [],
        "expertType": "",
        "meetingStartTime": DATE_START,
        "meetingEndTime": DATE_END,
        "queryHotListFlag": False,
        "sort": 2,
        "platform": "RESEARCH_PC",
    }
    my_input = token + str(keyword) + str(page)
    forum_input = token + str(keyword) + "   " + str(page)
    return _post_signed(
        f"{API_BASE}/forum/select/list", token, body, my_input, forum_input
    )


def main():
    token = _get_token()
    print(f"Token loaded. Searching {DATE_START} ~ {DATE_END}\n")

    all_items: dict[int, dict] = {}
    keyword_hits: dict[str, list[int]] = {}

    for kw in KEYWORDS:
        keyword_hits[kw] = []
        page = 1
        while True:
            try:
                resp = search(token, kw, page=page)
            except Exception as e:
                print(f"  [{kw} p{page}] ERROR: {e}")
                break

            if resp.get("code") != 200:
                print(f"  [{kw} p{page}] API error: {resp.get('message')}")
                break

            result = resp.get("result") or {}
            forum_list = result.get("forumList") or []
            total = result.get("total", 0)

            in_range = []
            for item in forum_list:
                mt = (item.get("meetingTime") or "")[:10]
                if not mt:
                    continue
                if DATE_START[:10] <= mt <= DATE_END[:10]:
                    in_range.append(item)
                    if item["id"] not in all_items:
                        all_items[item["id"]] = item
                    keyword_hits[kw].append(item["id"])

            print(
                f"  [{kw}] page {page}: {len(forum_list)} returned, "
                f"{len(in_range)} in date range (total={total})"
            )

            if len(forum_list) < 50 or page >= 5:
                break
            page += 1

    print("\n" + "=" * 80)
    print(f"Unique candidates in date range: {len(all_items)}")
    print("=" * 80 + "\n")

    # Sort by date desc
    items = sorted(
        all_items.values(),
        key=lambda x: (x.get("meetingTime") or ""),
        reverse=True,
    )

    # Tag each item with which keywords matched it
    id_to_keywords: dict[int, list[str]] = {}
    for kw, ids in keyword_hits.items():
        for iid in ids:
            id_to_keywords.setdefault(iid, []).append(kw)

    # Print full list, marking ticker matches
    print(f"{'#':<3} {'Date':<11} {'Tickers':<14} {'Industry':<12} Title  /  Keywords")
    print("-" * 100)
    for i, item in enumerate(items, 1):
        date = (item.get("meetingTime") or "")[:10]
        tickers = item.get("relatedTargets") or []
        tickers_str = ",".join(tickers) if tickers else "-"
        industry = (item.get("industry") or "")[:10]
        title = (item.get("title") or "")[:60]
        kws = ",".join(id_to_keywords.get(item["id"], []))
        marker = " ★" if any(t in TARGET_TICKERS for t in tickers) else "  "
        print(f"{i:<3}{marker}{date:<11} {tickers_str:<14} {industry:<12} {title}")
        print(f"     id={item['id']}  matched_kw=[{kws}]")
        summary = (item.get("summary") or "").replace("\n", " ")[:140]
        if summary:
            print(f"     摘要: {summary}")
        print()


if __name__ == "__main__":
    main()
