"""Quick probe to understand what the list API returns under various conditions."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inv_newsletter.meritco import _get_token, _post_signed, API_BASE


def call(token: str, body: dict, label: str):
    keyword = body.get("keyword", "")
    page = body.get("page", 1)
    my_input = token + str(keyword) + str(page)
    forum_input = token + str(keyword) + "   " + str(page)
    try:
        resp = _post_signed(
            f"{API_BASE}/forum/select/list", token, body, my_input, forum_input
        )
        result = resp.get("result") or {}
        forum_list = result.get("forumList") or []
        total = result.get("total")
        print(f"[{label}] code={resp.get('code')} total={total} returned={len(forum_list)}")
        if forum_list:
            sample = forum_list[0]
            print(f"  sample id={sample.get('id')} date={sample.get('meetingTime', '')[:10]} "
                  f"tickers={sample.get('relatedTargets')} title={sample.get('title','')[:60]}")
        if not forum_list and resp.get("message"):
            print(f"  message: {resp.get('message')}")
    except Exception as e:
        print(f"[{label}] EXCEPTION: {e}")


def base_body() -> dict:
    return {
        "forumId": None,
        "page": 1,
        "pageSize": 20,
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
        "keyword": "",
        "type": 2,
        "industryList": [],
        "expertType": "",
        "meetingStartTime": "",
        "meetingEndTime": "",
        "queryHotListFlag": False,
        "sort": 2,
        "platform": "RESEARCH_PC",
    }


def main():
    token = _get_token()

    # 1. Baseline — no keyword, no date range
    b = base_body()
    call(token, b, "no-keyword no-date")

    # 2. Keyword only, no date
    for kw in ["DCI", "光模块", "Nokia", "诺基亚"]:
        b = base_body()
        b["keyword"] = kw
        call(token, b, f"keyword={kw} no-date")

    # 3. Keyword + date range (the failing case)
    b = base_body()
    b["keyword"] = "光模块"
    b["meetingStartTime"] = "2026-03-01"
    b["meetingEndTime"] = "2026-05-31"
    call(token, b, "keyword=光模块 + date 03-01~05-31 (string YYYY-MM-DD)")

    # 4. Try date with HH:MM:SS format
    b = base_body()
    b["keyword"] = "光模块"
    b["meetingStartTime"] = "2026-03-01 00:00:00"
    b["meetingEndTime"] = "2026-05-31 23:59:59"
    call(token, b, "keyword=光模块 + date with HH:MM:SS")

    # 5. publishTime instead
    b = base_body()
    b["keyword"] = "光模块"
    b["publishTime"] = "近三个月"
    call(token, b, "keyword=光模块 + publishTime=近三个月")

    # 6. Dump full first response for shape inspection
    print("\n--- full response sample (no keyword, page 1) ---")
    b = base_body()
    keyword = b["keyword"]
    page = b["page"]
    my_input = token + str(keyword) + str(page)
    forum_input = token + str(keyword) + "   " + str(page)
    resp = _post_signed(
        f"{API_BASE}/forum/select/list", token, b, my_input, forum_input
    )
    print(json.dumps({k: ("..." if k == "result" else v) for k, v in resp.items()}, ensure_ascii=False, indent=2))
    result = resp.get("result") or {}
    print("result keys:", list(result.keys()))
    fl = result.get("forumList") or []
    if fl:
        print("\nfirst item keys:", list(fl[0].keys()))


if __name__ == "__main__":
    main()
