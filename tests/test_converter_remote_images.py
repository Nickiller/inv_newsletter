"""Substack 邮件（substackcdn 远程图片）下载与过滤的单元测试。不走网络。"""

from __future__ import annotations

from unittest.mock import patch

from inv_newsletter.converter import _is_substack_content_image, convert_email

CDN = "https://substackcdn.com/image/fetch/$s_!WTI5!,w_1100,c_limit,f_auto,q_auto:good,fl_progressive:steep/"
CONTENT = CDN + "https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2Fabc_1456x800.png"
ICON = CDN + "https%3A%2F%2Fsubstack.com%2Ficon%2FLucideHeart%3Fv%3D4"
CHROME = CDN + "https%3A%2F%2Fsubstack.com%2Fimg%2Femail%2Fstart-your-own.png"
PIXEL = "https://eotrx.substackcdn.com/o/56bd8b4d578bd3e6/p.gif?token=x"


def test_is_substack_content_image():
    assert _is_substack_content_image(CONTENT, "550")
    assert _is_substack_content_image(CONTENT, "")  # no declared width
    assert not _is_substack_content_image(CONTENT, "40")  # avatar/logo
    assert not _is_substack_content_image(ICON, "18")
    assert not _is_substack_content_image(ICON, "")
    assert not _is_substack_content_image(CHROME, "183")
    assert not _is_substack_content_image(PIXEL, "")


def _html():
    return (
        f'<p>Chart below</p><img src="{CONTENT}" width="550">'
        f'<img src="{ICON}" width="18"><img src="{CHROME}" width="183">'
        f'<img src="{PIXEL}"><img src="https://example.com/bank-logo.png">'
    )


def test_downloads_content_images_and_drops_icons():
    with patch("inv_newsletter.converter._fetch_remote_image",
               return_value=(b"\x89PNG" + b"0" * 100, "image/png")) as fetch:
        result = convert_email(_html(), [], "TMTB EOD Wrap")
    fetch.assert_called_once_with(CONTENT)
    assert [i.filename for i in result.images] == ["img-001.png"]
    assert "./img-001.png" in result.markdown
    assert "LucideHeart" not in result.markdown
    assert "start-your-own" not in result.markdown
    # 非 substack 的远程图片保持原样（不下载）
    assert "https://example.com/bank-logo.png" in result.markdown


def test_failed_download_keeps_remote_url():
    with patch("inv_newsletter.converter._fetch_remote_image", return_value=None):
        result = convert_email(_html(), [], "TMTB EOD Wrap")
    assert result.images == []
    assert "substack-post-media" in result.markdown
