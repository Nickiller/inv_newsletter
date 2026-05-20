"""Phase 2 tests: taxonomy 注入、section/industry 重排、drift audit。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from inv_newsletter import summarizer
from inv_newsletter.summarizer import (
    _append_audit_footer,
    _drift_audit,
    _inject_taxonomy,
    _reorder_industries_within_section,
    _reorder_sections,
    _write_drift_logs,
)
from inv_newsletter.taxonomy import Taxonomy


# ── 1. Prompt injection ──────────────────────────────────────


def test_module_level_system_prompt_has_taxonomy_injected():
    assert "{{TAXONOMY_BLOCK}}" not in summarizer.SYSTEM_PROMPT
    assert "## AI 模型与平台" in summarizer.SYSTEM_PROMPT
    assert "**网络安全**" in summarizer.SYSTEM_PROMPT
    # Sanity: prompt still has the role / output_format scaffolding
    assert "<role>" in summarizer.SYSTEM_PROMPT
    assert "<output_format>" in summarizer.SYSTEM_PROMPT


def test_inject_taxonomy_missing_placeholder_raises():
    with pytest.raises(RuntimeError, match="placeholder"):
        _inject_taxonomy("no placeholder here")


def test_inject_taxonomy_with_custom_taxonomy(tmp_path):
    yaml_path = tmp_path / "tiny.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """\
            version: 1
            sectors:
              - name: SectorX
                industries:
                  - name: IndX
                    tickers:
                      - {ticker: XXX, company: Xco}
            """
        ),
        encoding="utf-8",
    )
    tax = Taxonomy.load(yaml_path)
    out = _inject_taxonomy("BEFORE\n{{TAXONOMY_BLOCK}}\nAFTER", taxonomy=tax)
    assert "## SectorX" in out
    assert "XXX (Xco)" in out
    assert "BEFORE" in out and "AFTER" in out


# ── 2. Section / industry reorder ─────────────────────────────


_SAMPLE_DIGEST = """\
# Daily Research Digest — 2026-05-19

## 软件与SaaS

### 网络安全

#### PANW — body

### 平台型 / 大盘软件

#### MSFT — body

## 半导体与硬件

### 存储 (DRAM / NAND / HBM)

#### MU — body

### GPU / AI 加速器

#### NVDA — body

## AI 模型与平台

### Foundation Models

#### ANTH — body

## 本周关注
- something
"""


def test_reorder_sections_puts_ai_first_and_zhouguanzhu_last():
    out = _reorder_sections(_SAMPLE_DIGEST)
    # AI 模型与平台 should appear before 半导体与硬件
    ai_pos = out.find("## AI 模型与平台")
    semi_pos = out.find("## 半导体与硬件")
    sw_pos = out.find("## 软件与SaaS")
    other_pos = out.find("## 其他")  # not present
    zhou_pos = out.find("## 本周关注")
    assert ai_pos != -1 and semi_pos != -1 and sw_pos != -1 and zhou_pos != -1
    assert ai_pos < semi_pos < sw_pos < zhou_pos
    # 其他 not in sample
    assert other_pos == -1


def test_reorder_industries_within_semi_section():
    out = _reorder_sections(_SAMPLE_DIGEST)
    semi_start = out.index("\n## 半导体与硬件") + 1
    semi_end = out.index("\n## ", semi_start + 3) + 1
    semi_chunk = out[semi_start:semi_end]
    gpu_pos = semi_chunk.find("### GPU / AI 加速器")
    store_pos = semi_chunk.find("### 存储 (DRAM / NAND / HBM)")
    # taxonomy puts GPU / AI 加速器 before 存储
    assert gpu_pos != -1 and store_pos != -1
    assert gpu_pos < store_pos


def test_reorder_industries_keeps_unknown_industries_at_end():
    digest = textwrap.dedent(
        """\
        # title

        ## 半导体与硬件

        ### 月球开采

        body

        ### GPU / AI 加速器

        #### NVDA — body
        """
    )
    out = _reorder_industries_within_section(
        digest.split("## 半导体与硬件")[1],
        "半导体与硬件",
        summarizer.get_default_taxonomy(),
    )
    gpu_pos = out.find("### GPU / AI 加速器")
    moon_pos = out.find("### 月球开采")
    assert gpu_pos != -1 and moon_pos != -1
    # Known industry goes first, unknown after
    assert gpu_pos < moon_pos


def test_reorder_sections_preserves_h1_preamble():
    out = _reorder_sections(_SAMPLE_DIGEST)
    assert out.startswith("# Daily Research Digest")


# ── 3. Drift audit ───────────────────────────────────────────


def test_drift_audit_detects_misclassified_ticker():
    digest = textwrap.dedent(
        """\
        # title

        ## 软件与SaaS

        #### NVDA — wrong sector
        body

        ## 半导体与硬件

        #### MU — right sector
        body
        """
    )
    report = _drift_audit(digest)
    assert len(report["misclassified"]) == 1
    item = report["misclassified"][0]
    assert item["canonical_ticker"] == "NVDA"
    assert item["found_in"] == "软件与SaaS"
    assert item["expected"] == "半导体与硬件"
    assert report["unmapped"] == []


def test_drift_audit_detects_unmapped_ticker():
    digest = textwrap.dedent(
        """\
        # title

        ## 半导体与硬件

        #### ZZZZ — totally fake ticker
        body
        """
    )
    report = _drift_audit(digest)
    assert len(report["unmapped"]) == 1
    assert report["unmapped"][0]["ticker"] == "ZZZZ"
    assert report["misclassified"] == []


def test_drift_audit_ignores_body_text_mentions():
    """If NVDA is mentioned in body text of TSMC section, not flagged.

    Only #### headings count as classification claims.
    """
    digest = textwrap.dedent(
        """\
        ## 半导体与硬件

        #### TSM — TSMC's NVDA exposure increased
        Body mentions NVDA, AMD, INTC freely.
        """
    )
    report = _drift_audit(digest)
    assert report["misclassified"] == []
    assert report["unmapped"] == []


def test_drift_audit_handles_compound_ticker_headings():
    """e.g. '#### SK Hynix — ...' — multi-word company name with alias."""
    digest = textwrap.dedent(
        """\
        ## 半导体与硬件

        #### SK Hynix — +7.7%
        body
        """
    )
    report = _drift_audit(digest)
    assert report["misclassified"] == []
    assert report["unmapped"] == []


def test_write_drift_logs_appends_lines(tmp_path):
    report = {
        "misclassified": [
            {
                "ticker": "NVDA",
                "canonical_ticker": "NVDA",
                "found_in": "软件与SaaS",
                "expected": "半导体与硬件",
                "heading": "#### NVDA — wrong",
            }
        ],
        "unmapped": [
            {"ticker": "ZZZZ", "found_in": "半导体与硬件", "heading": "#### ZZZZ — fake"}
        ],
    }
    _write_drift_logs(report, "2026-05-19", tmp_path)
    drift = (tmp_path / "digest_drift.log").read_text(encoding="utf-8")
    unmapped = (tmp_path / "unmapped_tickers.log").read_text(encoding="utf-8")
    assert "2026-05-19" in drift
    assert "NVDA" in drift
    assert "expected=半导体与硬件" in drift
    assert "2026-05-19" in unmapped
    assert "ZZZZ" in unmapped


def test_audit_footer_clean_when_no_drift():
    digest = "## 半导体与硬件\n\n#### NVDA — body\n"
    out = _append_audit_footer(digest, {"misclassified": [], "unmapped": []}, "2026-05-19")
    assert "audit: clean" in out


def test_drift_audit_accepts_hyperscaler_in_ai_platform():
    """GOOGL 主分类是 互联网，但 also_in 包含 AI 模型与平台 / Foundation Models —
    讨论 Gemini 时把 GOOGL 放在 AI 模型与平台不应被标为 drift。
    """
    digest = textwrap.dedent(
        """\
        # title

        ## AI 模型与平台

        ### Foundation Models

        #### GOOGL — Gemini 2.5 发布，多模态能力大幅提升
        body about Gemini.

        ## 互联网与数字广告

        ### 大型互联网平台

        #### GOOGL — Q4 ad revenue +12% y/y
        body about ad business.
        """
    )
    report = _drift_audit(digest)
    # 两个 GOOGL heading 都应被接受（主分类 + also_in）
    assert report["misclassified"] == [], report["misclassified"]
    assert report["unmapped"] == []


def test_drift_audit_still_catches_truly_wrong_sector():
    """NVDA 没有 also_in，放在 软件与SaaS 应被标为 drift。"""
    digest = textwrap.dedent(
        """\
        ## 软件与SaaS

        #### NVDA — 误放
        body
        """
    )
    report = _drift_audit(digest)
    assert len(report["misclassified"]) == 1
    assert report["misclassified"][0]["canonical_ticker"] == "NVDA"
    assert report["misclassified"][0]["kind"] == "ticker"


def test_drift_audit_catches_industry_in_wrong_sector():
    """LLM 把 `### 游戏` 放进 `## 软件与SaaS`，但 taxonomy 里 游戏 属于 互联网。"""
    digest = textwrap.dedent(
        """\
        ## 软件与SaaS

        ### 游戏

        #### TTWO — body
        """
    )
    report = _drift_audit(digest)
    # 应抓到两个 misclassified：industry "游戏" + ticker TTWO（两次警告 OK，不同维度）
    industries = [i for i in report["misclassified"] if i.get("kind") == "industry"]
    tickers = [i for i in report["misclassified"] if i.get("kind") == "ticker"]
    assert len(industries) == 1
    assert industries[0]["industry"] == "游戏"
    assert industries[0]["found_in"] == "软件与SaaS"
    assert industries[0]["expected"] == "互联网与数字广告"
    assert len(tickers) == 1
    assert tickers[0]["canonical_ticker"] == "TTWO"


def test_drift_audit_industry_correctly_placed_not_flagged():
    """`### 网络安全` 放在 `## 软件与SaaS` 是对的 — 不应报警。"""
    digest = textwrap.dedent(
        """\
        ## 软件与SaaS

        ### 网络安全

        #### PANW — body
        """
    )
    report = _drift_audit(digest)
    assert report["misclassified"] == []
    assert report["unmapped"] == []


def test_drift_audit_h3_ticker_fallback():
    """LLM 偷懒把 ticker 写成 ### 级（跳过 #### 级），仍应被抓到 drift。"""
    digest = textwrap.dedent(
        """\
        ## 软件与SaaS

        ### CRCL — Stablecoin / Clarity Act 时间表
        body about CRCL.
        """
    )
    report = _drift_audit(digest)
    # CRCL 主分类是 互联网/Fintech，放在 SaaS 应被 H3 fallback 抓到
    ticker_drifts = [i for i in report["misclassified"] if i.get("kind") == "ticker"]
    assert len(ticker_drifts) == 1
    assert ticker_drifts[0]["canonical_ticker"] == "CRCL"
    assert ticker_drifts[0]["found_in"] == "软件与SaaS"


def test_drift_audit_theme_h3_skipped_silently():
    """主题型 `### XXX` 标题不报警（如 `### 存储超级周期 + LTA 重估框架`）。"""
    digest = textwrap.dedent(
        """\
        ## 半导体与硬件

        ### 存储超级周期 + LTA 重估框架

        #### MU — body
        """
    )
    report = _drift_audit(digest)
    # 标题不是已知 industry、也不是 ticker shape → 不应报警
    assert report["misclassified"] == []
    assert report["unmapped"] == []


def test_write_drift_logs_includes_kind(tmp_path):
    report = {
        "misclassified": [
            {
                "kind": "industry",
                "industry": "游戏",
                "found_in": "软件与SaaS",
                "expected": "互联网与数字广告",
                "heading": "### 游戏",
            },
            {
                "kind": "ticker",
                "ticker": "TTWO",
                "canonical_ticker": "TTWO",
                "found_in": "软件与SaaS",
                "expected": "互联网与数字广告",
                "heading": "#### TTWO — ...",
            },
        ],
        "unmapped": [],
    }
    _write_drift_logs(report, "2026-05-19", tmp_path)
    drift = (tmp_path / "digest_drift.log").read_text(encoding="utf-8")
    assert "industry" in drift
    assert "游戏" in drift
    assert "ticker" in drift
    assert "TTWO" in drift


def test_audit_footer_lists_offenders():
    report = {
        "misclassified": [
            {
                "ticker": "NVDA",
                "canonical_ticker": "NVDA",
                "found_in": "软件与SaaS",
                "expected": "半导体与硬件",
                "heading": "#### NVDA",
            }
        ],
        "unmapped": [
            {"ticker": "ZZZZ", "found_in": "半导体与硬件", "heading": "#### ZZZZ"}
        ],
    }
    out = _append_audit_footer("digest body", report, "2026-05-19")
    assert "<!--" in out and "-->" in out
    assert "misclassified=1" in out
    assert "unmapped=1" in out
    assert "NVDA in 软件与SaaS → expected 半导体与硬件" in out
    assert "unmapped: ZZZZ in 半导体与硬件" in out
