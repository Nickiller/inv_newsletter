"""Taxonomy 加载、查询、顺序、prompt 渲染单元测试。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from inv_newsletter.taxonomy import (
    DEFAULT_TAXONOMY_PATH,
    Taxonomy,
    _normalize_symbol,
    get_default_taxonomy,
)


# ── 默认 taxonomy.yaml 的端到端校验 ─────────────────────────────


def test_default_taxonomy_loads():
    tax = Taxonomy.load()
    assert tax.sectors, "taxonomy.yaml 没加载出任何 sector"


def test_get_default_taxonomy_is_cached():
    a = get_default_taxonomy()
    b = get_default_taxonomy()
    assert a is b


def test_sector_order_matches_yaml():
    tax = Taxonomy.load()
    raw = yaml.safe_load(DEFAULT_TAXONOMY_PATH.read_text(encoding="utf-8"))
    expected = [s["name"] for s in raw["sectors"]]
    assert tax.sector_order() == expected


def test_industry_order_matches_yaml_for_each_sector():
    tax = Taxonomy.load()
    raw = yaml.safe_load(DEFAULT_TAXONOMY_PATH.read_text(encoding="utf-8"))
    for s in raw["sectors"]:
        expected = [i["name"] for i in (s.get("industries") or [])]
        assert tax.industry_order(s["name"]) == expected, f"industry order mismatch for {s['name']}"


def test_classify_known_tickers_in_default():
    tax = Taxonomy.load()
    # 仅校验无歧义、不易跨 sector 的核心 ticker（避免被用户编辑 taxonomy.yaml 时频繁踩到）
    cases = [
        ("NVDA", "半导体与硬件", "GPU / AI 加速器"),
        ("PANW", "软件与SaaS", "网络安全"),
        ("CRWV", "半导体与硬件", "先进 AI 算力 / GPU 云"),
        ("NBIS", "半导体与硬件", "先进 AI 算力 / GPU 云"),
        ("ANET", "半导体与硬件", "网络 / 光通信 / AI 连接"),
        ("TMUS", "其他", "电信 / 通信运营商"),
    ]
    for ticker, sector, industry in cases:
        result = tax.classify(ticker)
        assert result is not None, f"{ticker} should classify"
        assert result[0] == sector, f"{ticker} sector: {result[0]} != {sector}"
        assert result[1] == industry, f"{ticker} industry: {result[1]} != {industry}"


def test_no_duplicate_canonical_tickers_in_default():
    """同一 canonical ticker 不应出现在多个 (sector, industry) 位置。

    一旦出现，loader 的 first-write-wins 会让"晚到者"被静默忽略，配置意图与
    实际行为分裂。本测试用 xfail/pytest.warns 形式列出当前重复，方便人工 review。
    """
    tax = Taxonomy.load()
    seen: dict[str, tuple[str, str]] = {}
    duplicates: list[tuple[str, tuple[str, str], tuple[str, str]]] = []
    for sector in tax.sectors:
        for industry in sector.industries:
            for entry in industry.tickers:
                key = entry.ticker.upper()
                if key in seen:
                    duplicates.append((entry.ticker, seen[key], (sector.name, industry.name)))
                else:
                    seen[key] = (sector.name, industry.name)
    if duplicates:
        msg_lines = ["发现重复 ticker（loader 取首次出现，其余被忽略）："]
        for tk, first, second in duplicates:
            msg_lines.append(f"  - {tk}: 首次 {first[0]} / {first[1]}  →  重复 {second[0]} / {second[1]}")
        pytest.fail("\n".join(msg_lines))


def test_classify_unknown_returns_none():
    tax = Taxonomy.load()
    assert tax.classify("ZZZZZ_UNKNOWN_TICKER") is None


def test_classify_case_and_prefix_insensitive():
    tax = Taxonomy.load()
    upper = tax.classify("NVDA")
    lower = tax.classify("nvda")
    dollar = tax.classify("$NVDA")
    assert upper is not None
    assert upper == lower == dollar


def test_classify_company_alias():
    tax = Taxonomy.load()
    # 英伟达 是 NVDA 别名
    by_alias = tax.classify("英伟达")
    by_ticker = tax.classify("NVDA")
    assert by_alias is not None
    assert by_alias == by_ticker


def test_classify_company_name():
    tax = Taxonomy.load()
    # 公司全名也能 classify
    by_company = tax.classify("Palo Alto Networks")
    by_ticker = tax.classify("PANW")
    assert by_company is not None
    assert by_company == by_ticker


def test_known_symbols_includes_tickers_aliases_companies():
    tax = Taxonomy.load()
    syms = tax.known_symbols()
    # ticker
    assert _normalize_symbol("NVDA") in syms
    # alias
    assert _normalize_symbol("英伟达") in syms
    # company
    assert _normalize_symbol("Palo Alto Networks") in syms


def test_render_prompt_block_is_deterministic():
    tax = Taxonomy.load()
    a = tax.render_prompt_block()
    b = tax.render_prompt_block()
    assert a == b
    # contains sector + industry markers
    assert "## AI 模型与平台" in a
    assert "## 半导体与硬件" in a
    assert "**网络安全**" in a
    assert "PANW" in a


def test_render_prompt_block_handles_empty_industries():
    tax = Taxonomy.load()
    block = tax.render_prompt_block()
    # 本周关注 没有 industries — 不应该 crash
    assert "## 本周关注" in block


# ── 用一个小型 YAML fixture 测试 loader 行为 ────────────────────


_FIXTURE_YAML = textwrap.dedent(
    """\
    version: 1
    sectors:
      - name: SectorA
        description: first sector
        industries:
          - name: IndA1
            tickers:
              - {ticker: AAA, company: Alpha Co, aliases: [Alpha, 阿尔法]}
              - {ticker: BBB, company: Beta Co}
          - name: IndA2
            tickers:
              - {ticker: CCC, company: Charlie Co, notes: "边界 case"}
      - name: SectorB
        industries: []
    hard_excluded:
      reasons: [no biotech]
      sectors: [Biotech]
    """
)


@pytest.fixture
def fixture_taxonomy(tmp_path: Path) -> Taxonomy:
    p = tmp_path / "fixture_taxonomy.yaml"
    p.write_text(_FIXTURE_YAML, encoding="utf-8")
    return Taxonomy.load(p)


def test_fixture_basic_structure(fixture_taxonomy: Taxonomy):
    assert fixture_taxonomy.sector_order() == ["SectorA", "SectorB"]
    assert fixture_taxonomy.industry_order("SectorA") == ["IndA1", "IndA2"]
    assert fixture_taxonomy.industry_order("SectorB") == []


def test_fixture_classify(fixture_taxonomy: Taxonomy):
    assert fixture_taxonomy.classify("AAA") == ("SectorA", "IndA1", "AAA")
    assert fixture_taxonomy.classify("阿尔法") == ("SectorA", "IndA1", "AAA")
    assert fixture_taxonomy.classify("Alpha Co") == ("SectorA", "IndA1", "AAA")
    assert fixture_taxonomy.classify("CCC") == ("SectorA", "IndA2", "CCC")
    assert fixture_taxonomy.classify("ZZZ") is None


def test_fixture_hard_excluded(fixture_taxonomy: Taxonomy):
    assert "Biotech" in fixture_taxonomy.hard_excluded.sectors
    assert "no biotech" in fixture_taxonomy.hard_excluded.reasons


def test_fixture_render_prompt_block_skips_empty_industries(fixture_taxonomy: Taxonomy):
    block = fixture_taxonomy.render_prompt_block()
    assert "## SectorA" in block
    assert "**IndA1**" in block
    assert "AAA (Alpha Co)" in block
    # SectorB has empty industries list → meta section, just the header
    assert "## SectorB" in block
    assert "meta 板块" in block or "无 ticker" in block


def test_render_prompt_block_includes_theme_only_industries(tmp_path: Path):
    """Theme-only industries（tickers: []）应仍渲染到 prompt block 里。"""
    p = tmp_path / "theme.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            version: 1
            sectors:
              - name: MacroSector
                industries:
                  - name: 利率 / 汇率
                    description: 10年期、美元、JPY 等
                    tickers: []
                  - name: ETFs
                    tickers:
                      - {ticker: SPY, company: SPDR S&P 500}
            """
        ),
        encoding="utf-8",
    )
    tax = Taxonomy.load(p)
    block = tax.render_prompt_block()
    assert "**利率 / 汇率**" in block
    assert "theme-led" in block
    assert "10年期" in block
    assert "SPY (SPDR S&P 500)" in block


def test_default_taxonomy_render_includes_macro_themes():
    """回归：宏观与市场 sector 的 theme-only industry 必须出现在 prompt block。"""
    tax = Taxonomy.load()
    block = tax.render_prompt_block()
    assert "**利率 / 汇率 / 大宗**" in block
    assert "**Factor / Momentum / Rotation**" in block
    assert "**仓位 / 资金流 / Sentiment**" in block
    assert "**地缘 / 政策 / 关税**" in block
    assert "**IPO / 一级市场**" in block


# ── normalize_symbol 行为 ─────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NVDA", "NVDA"),
        ("nvda", "NVDA"),
        ("$NVDA", "NVDA"),
        (" $nvda ", "NVDA"),
        ("SK Hynix", "SKHYNIX"),
        ("SK_HYNIX", "SKHYNIX"),
        ("Palo Alto Networks", "PALOALTONETWORKS"),
        ("", ""),
    ],
)
def test_normalize_symbol(raw, expected):
    assert _normalize_symbol(raw) == expected


# ── 防御 YAML 1.1 boolean 陷阱（ON / OFF / YES / NO / TRUE / FALSE）─────


def test_loader_rejects_yaml_boolean_ticker(tmp_path: Path):
    """ticker: ON 不加引号会被 PyYAML 解析为 True；loader 必须报错而非静默。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            version: 1
            sectors:
              - name: S
                industries:
                  - name: I
                    tickers:
                      - {ticker: ON, company: onsemi}
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ticker"):
        Taxonomy.load(bad)


def test_loader_accepts_quoted_yaml_boolean_ticker(tmp_path: Path):
    good = tmp_path / "good.yaml"
    good.write_text(
        textwrap.dedent(
            """\
            version: 1
            sectors:
              - name: S
                industries:
                  - name: I
                    tickers:
                      - {ticker: "ON", company: onsemi}
            """
        ),
        encoding="utf-8",
    )
    tax = Taxonomy.load(good)
    assert tax.classify("ON") == ("S", "I", "ON")


def test_default_taxonomy_onsemi_renders_correctly():
    """回归测试：ON (onsemi) 不应被渲染成 True。"""
    tax = Taxonomy.load()
    block = tax.render_prompt_block()
    assert "True (onsemi)" not in block
    assert "ON (onsemi)" in block


# ── also_in / accepted_locations ──────────────────────────────


def test_default_hyperscalers_have_ai_secondary_location():
    """GOOGL/META/MSFT/BABA/AMZN 主分类是 互联网/SaaS，但 AI 产品讨论时也可
    落在 AI 模型与平台 / Foundation Models —— accepted_locations 应返回两个。
    """
    tax = Taxonomy.load()
    for tk in ["GOOGL", "META", "MSFT", "BABA", "AMZN"]:
        locs = tax.accepted_locations(tk)
        assert ("AI 模型与平台", "Foundation Models") in locs, (
            f"{tk} 应在 also_in 包含 AI 模型与平台 / Foundation Models，实际 locations={locs}"
        )
        # 主分类应该是第一个
        primary = tax.classify(tk)
        assert locs[0] == (primary[0], primary[1])


def test_accepted_locations_unknown_returns_empty():
    tax = Taxonomy.load()
    assert tax.accepted_locations("ZZZZZ_UNKNOWN") == []


def test_pure_play_ai_lab_has_no_also_in():
    """ANTH / OAI 是 pure-play AI lab，accepted_locations 应只返回主分类一个。"""
    tax = Taxonomy.load()
    locs = tax.accepted_locations("ANTH")
    assert len(locs) == 1
    assert locs[0] == ("AI 模型与平台", "Foundation Models")


def test_also_in_loader_validates_required_fields(tmp_path: Path):
    """also_in 条目缺 sector 或 industry 时 loader 必须报错。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            version: 1
            sectors:
              - name: S
                industries:
                  - name: I
                    tickers:
                      - {ticker: AAA, company: Aco, also_in: [{sector: "OtherSector"}]}
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="also_in"):
        Taxonomy.load(bad)


def test_also_in_loader_accepts_well_formed(tmp_path: Path):
    good = tmp_path / "good.yaml"
    good.write_text(
        textwrap.dedent(
            """\
            version: 1
            sectors:
              - name: SectorPrimary
                industries:
                  - name: IndPrimary
                    tickers:
                      - ticker: AAA
                        company: Aco
                        also_in:
                          - {sector: "SectorAlt", industry: "IndAlt"}
              - name: SectorAlt
                industries:
                  - name: IndAlt
                    tickers: []
            """
        ),
        encoding="utf-8",
    )
    tax = Taxonomy.load(good)
    locs = tax.accepted_locations("AAA")
    assert locs == [("SectorPrimary", "IndPrimary"), ("SectorAlt", "IndAlt")]
