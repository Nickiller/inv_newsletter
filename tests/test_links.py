"""追踪链接还原（Substack / Resend / Slack）单元测试。不走网络。"""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

from inv_newsletter.converter import convert_email
from inv_newsletter.links import clean_tracking_url


def _jwt(payload: dict) -> str:
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{seg}.sig"


POST = "https://www.tmtbreakout.com/p/tmtb-morning-wrap-c2e?utm_campaign=email-post&r=695y2q&token=eyJ1c2Vy&utm_source=substack"
JWT_REDIRECT = "https://substack.com/redirect/2/" + _jwt({"e": POST, "u": 378191042})
UUID_REDIRECT = "https://substack.com/redirect/29e3c1dd-9113-43ff-a055-99f229c0ed97?j=eyJ1IjoiNjk1eTJxIn0.sig"
RESEND = ("https://23ed0f39.ap-northeast-1.resend-clicks-a.com/CL0/"
          "https:%2F%2Fwww.bloomberg.com%2Fnews%2Farticles%2Fabc%3Futm_source%3Dx/1/0106-000000/sig=258")
RESEND_SLACK = ("https://23ed0f39.ap-northeast-1.resend-clicks-a.com/CL0/"
                "https:%2F%2Fapp.slack.com%2Fclient%2FT0A7%2FC0A7/1/0106-000000/sig=258")


def test_jwt_redirect_decoded_and_subscriber_params_stripped():
    assert clean_tracking_url(JWT_REDIRECT) == "https://www.tmtbreakout.com/p/tmtb-morning-wrap-c2e"


def test_bare_payload_jwt_redirect_decoded():
    seg = base64.urlsafe_b64encode(json.dumps({"e": POST}).encode()).decode().rstrip("=")
    assert clean_tracking_url(f"https://substack.com/redirect/2/{seg}.sigsig") == \
        "https://www.tmtbreakout.com/p/tmtb-morning-wrap-c2e"


def test_uuid_redirect_resolved_without_subscriber_token():
    with patch("inv_newsletter.links._resolve_anonymous",
               return_value="https://www.reuters.com/a/b/?utm_source=substack&utm_medium=email") as res:
        assert clean_tracking_url(UUID_REDIRECT) == "https://www.reuters.com/a/b/"
    res.assert_called_once_with("https://substack.com/redirect/29e3c1dd-9113-43ff-a055-99f229c0ed97")


def test_unresolvable_redirect_dropped():
    with patch("inv_newsletter.links._resolve_anonymous", return_value=None):
        assert clean_tracking_url(UUID_REDIRECT) is None


def test_resend_unwrapped_and_slack_dropped():
    assert clean_tracking_url(RESEND) == "https://www.bloomberg.com/news/articles/abc"
    assert clean_tracking_url(RESEND_SLACK) is None


def test_substack_account_actions_dropped_and_others_untouched():
    assert clean_tracking_url("https://www.tmtbreakout.com/action/disable_email?token=x") is None
    assert clean_tracking_url("https://substack.com/app-link/post?publication_id=1&post_id=2&token=x") is None
    assert clean_tracking_url("https://markets.jpmorgan.com/research/x?id=1") == "https://markets.jpmorgan.com/research/x?id=1"


def test_convert_email_rewrites_links():
    html = (f'<p>See <a href="{JWT_REDIRECT}">the post</a>, <a href="{RESEND}">Bloomberg</a>, '
            f'<a href="{RESEND_SLACK}">TMTB Slack</a>.</p>')
    md = convert_email(html, [], "x").markdown
    assert "[the post](https://www.tmtbreakout.com/p/tmtb-morning-wrap-c2e)" in md
    assert "[Bloomberg](https://www.bloomberg.com/news/articles/abc)" in md
    assert "TMTB Slack" in md and "slack.com" not in md
    assert "695y2q" not in md and "redirect" not in md
