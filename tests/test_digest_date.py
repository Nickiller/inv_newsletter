"""邮件归档日期（digest date）与 weekly 按收件 UTC 日期筛选的单元测试。"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from inv_newsletter.storage import digest_date
from inv_newsletter.weekly import _load_weekly_emails, _week_dates


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "received_utc, expected",
    [
        # TMTB Morning Wrap 13:32 UTC = CST 21:32 → 当天开盘附近的日报
        ("2026-11-16T13:32:04", date(2026, 11, 16)),
        # TMTB Podcast Intel 21:12 UTC = CST 次日 05:12 → 次日日报
        ("2026-11-16T21:12:17", date(2026, 11, 17)),
        # TMTB EOD Wrap 23:18 UTC = CST 次日 07:18 → 次日日报
        ("2026-11-16T23:18:10", date(2026, 11, 17)),
        # 投行早间邮件（UTC 早上）不受影响
        ("2026-11-16T07:48:00", date(2026, 11, 16)),
        # 截止边界：CST 22:59 当天，CST 23:00 归次日
        ("2026-11-16T14:59:59", date(2026, 11, 16)),
        ("2026-11-16T15:00:00", date(2026, 11, 17)),
    ],
)
def test_digest_date(received_utc, expected):
    assert digest_date(_utc(received_utc)) == expected


def _write_email(mail_dir, folder: str, slug: str, sender: str, received: str):
    d = mail_dir / folder / slug
    d.mkdir(parents=True)
    (d / "email.md").write_text(
        f'---\nsender_address: "{sender}"\nreceived_at: "{received}"\n---\n\n# x\n',
        encoding="utf-8",
    )


def test_weekly_selects_by_received_utc_date(tmp_path):
    sender = "jfavuzza@jefferies.com"
    week = _week_dates(date(2026, 11, 15))  # Mon 11/9 .. Sun 11/15
    # 上周日美股下午的邮件 → 存在本周一文件夹，但不属于本周
    _write_email(tmp_path, "2026-11-09", "a", sender, "2026-11-08T17:32:00+00:00")
    # 本周一正常邮件
    _write_email(tmp_path, "2026-11-09", "b", sender, "2026-11-09T12:00:00+00:00")
    # 本周日美股下午的邮件 → 存在下周一文件夹，但属于本周
    _write_email(tmp_path, "2026-11-16", "c", sender, "2026-11-15T17:32:00+00:00")
    # 下周一正常邮件 → 不属于本周
    _write_email(tmp_path, "2026-11-16", "d", sender, "2026-11-16T12:00:00+00:00")

    got = _load_weekly_emails(tmp_path, week, {sender})
    assert sorted(e["date"] for e in got) == ["2026-11-09", "2026-11-15"]
    assert sorted(e["filename"].split("/")[-2] for e in got) == ["b", "c"]
