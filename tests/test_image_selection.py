"""_select_key_images 的按发件人放宽规则（TMTB）单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from inv_newsletter.images import _select_key_images


def _make_images(d: Path, sizes_kb: list[int]) -> list[str]:
    names = []
    for i, kb in enumerate(sizes_kb, 1):
        name = f"img-{i:03d}.png"
        (d / name).write_bytes(b"0" * kb * 1024)
        names.append(name)
    return names


SIZES = [24, 161, 326, 34, 51, 103, 24, 48, 10, 52, 30, 48, 33, 21, 99, 46, 106, 3]


def test_default_policy_unchanged():
    d = Path(tempfile.mkdtemp())
    names = _make_images(d, SIZES)
    got = _select_key_images(d, names, "mark.schilsky@jpmorgan.com")
    assert [g["name"] for g in got] == ["img-002.png", "img-003.png", "img-005.png", "img-006.png", "img-008.png"]
    assert _select_key_images(d, names) == got  # no sender = default


def test_tmtb_keeps_small_tables_and_more_images():
    d = Path(tempfile.mkdtemp())
    names = _make_images(d, SIZES)
    got = _select_key_images(d, names, "TMTBreakout@substack.com")
    # 3KB 以下仍过滤；其余 17 张里取前 15 张
    assert len(got) == 15
    assert "img-009.png" in [g["name"] for g in got]  # 10KB P/E 表
    assert "img-018.png" not in [g["name"] for g in got]
