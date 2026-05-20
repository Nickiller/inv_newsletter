"""Sector / industry / ticker 分类表加载与查询。

权威表：``src/inv_newsletter/data/taxonomy.yaml``。
LLM 只负责抽 ticker 与判断；本模块负责 routing（ticker → sector/industry）
与顺序，调用方在 prompt 注入 + post-process 校验两端共用。
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml


DEFAULT_TAXONOMY_PATH = Path(__file__).parent / "data" / "taxonomy.yaml"


@dataclass(frozen=True)
class TickerEntry:
    ticker: str
    company: str
    aliases: tuple[str, ...] = ()
    notes: str = ""
    # Secondary (sector, industry) locations where this ticker is *also* a
    # legitimate fit. Example: GOOGL primary is 互联网 / 大型互联网平台 but AI
    # product discussions (Gemini/DeepMind/TPU) belong in AI 模型与平台 /
    # Foundation Models. Drift audit accepts any of the primary + secondary
    # locations without flagging misclassification.
    also_in: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Industry:
    name: str
    description: str
    tickers: tuple[TickerEntry, ...]


@dataclass(frozen=True)
class Sector:
    name: str
    description: str
    industries: tuple[Industry, ...]


@dataclass(frozen=True)
class HardExclusions:
    reasons: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()


@dataclass
class Taxonomy:
    sectors: tuple[Sector, ...]
    hard_excluded: HardExclusions = field(default_factory=HardExclusions)

    # ── 索引（构造后立即填充）─────────────────────────────────────
    _symbol_to_classification: dict[str, tuple[str, str, str]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        for sector in self.sectors:
            for industry in sector.industries:
                for entry in industry.tickers:
                    self._register(entry.ticker, sector.name, industry.name, entry.ticker)
                    for alias in entry.aliases:
                        self._register(alias, sector.name, industry.name, entry.ticker)
                    # company name 也支持 classify 查询
                    self._register(entry.company, sector.name, industry.name, entry.ticker)

    def _register(self, symbol: str, sector: str, industry: str, canonical_ticker: str) -> None:
        key = _normalize_symbol(symbol)
        if not key:
            return
        # 首次写入即为权威（YAML 中靠前者优先）；后续重复忽略
        self._symbol_to_classification.setdefault(key, (sector, industry, canonical_ticker))

    # ── 公共 API ─────────────────────────────────────────────────

    def classify(self, symbol: str) -> tuple[str, str, str] | None:
        """查 ticker / 别名 / 公司名 → (sector, industry, canonical_ticker)。

        大小写无关、去除 ``$`` 前缀；找不到返回 ``None``。
        返回**主分类**；用 ``accepted_locations`` 查多重位置。
        """
        return self._symbol_to_classification.get(_normalize_symbol(symbol))

    def accepted_locations(self, symbol: str) -> list[tuple[str, str]]:
        """所有可接受的 (sector, industry) 位置：主分类 + ``also_in`` 副位置。

        用于 drift audit：ticker 出现在任一可接受位置都不算 drift。例 GOOGL
        既可在 互联网 / 大型互联网平台（主），也可在 AI 模型与平台 /
        Foundation Models（讨论 Gemini 时）。
        """
        primary = self.classify(symbol)
        if primary is None:
            return []
        locations: list[tuple[str, str]] = [(primary[0], primary[1])]
        canonical = primary[2]
        for sector in self.sectors:
            for industry in sector.industries:
                for entry in industry.tickers:
                    if entry.ticker == canonical:
                        for loc in entry.also_in:
                            if loc not in locations:
                                locations.append(loc)
                        return locations
        return locations

    def sector_order(self) -> list[str]:
        return [s.name for s in self.sectors]

    def industry_order(self, sector: str) -> list[str]:
        for s in self.sectors:
            if s.name == sector:
                return [i.name for i in s.industries]
        return []

    def industry_to_sector(self, industry_name: str) -> str | None:
        """反查 industry 名属于哪个 sector；找不到返回 None。

        用 ``_norm_industry_name`` 容忍空白/标点/大小写差异，但要求实质内容相等。
        例：``"游戏"`` → ``"互联网与数字广告"``；``"网络安全"`` → ``"软件与SaaS"``。
        """
        target = _norm_industry_name(industry_name)
        if not target:
            return None
        for sector in self.sectors:
            for industry in sector.industries:
                if _norm_industry_name(industry.name) == target:
                    return sector.name
        return None

    def known_symbols(self) -> set[str]:
        """Post-process 抽 ticker 时用作命中集。"""
        return set(self._symbol_to_classification.keys())

    def all_tickers(self) -> list[TickerEntry]:
        return [e for s in self.sectors for i in s.industries for e in i.tickers]

    def render_prompt_block(self) -> str:
        """渲染紧凑 markdown 表，供 digest prompt 注入。

        格式：
            ## <sector>
            - **<industry>**: TKR1 (Company), TKR2 (Company), ...
            - **<theme-only industry>** *(theme-led, 无 ticker)*: <description>

        Theme-only industry（``tickers: []``）也会渲染，避免 LLM 因 prompt 中
        看不到该 industry 而把相关主题降级到其他 sector。
        故意省略 aliases / notes，节省 token；归类指引由 prompt 上下文给。
        """
        lines: list[str] = []
        for sector in self.sectors:
            if not sector.industries:
                lines.append(f"## {sector.name}")
                lines.append("(meta 板块，无 ticker 归属)")
                lines.append("")
                continue
            lines.append(f"## {sector.name}")
            for industry in sector.industries:
                if industry.tickers:
                    ticker_strs = [
                        f"{e.ticker} ({e.company})" if e.company else e.ticker
                        for e in industry.tickers
                    ]
                    lines.append(f"- **{industry.name}**: {', '.join(ticker_strs)}")
                else:
                    # theme-only industry — render description so LLM sees the
                    # category and routes matching themes here instead of 其他.
                    desc = industry.description or "theme-led, 无 ticker"
                    lines.append(f"- **{industry.name}** *(theme-led)*: {desc}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Taxonomy":
        p = Path(path) if path else DEFAULT_TAXONOMY_PATH
        with p.open("r", encoding="utf-8") as fp:
            raw = yaml.safe_load(fp)
        return _from_raw(raw)


# ── 内部工具 ─────────────────────────────────────────────────────


_SYMBOL_STRIP_RE = re.compile(r"[\s\$_/\-（）()]+")
_INDUSTRY_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm_industry_name(name: str) -> str:
    """Normalize sector / industry name for comparison: strip all non-word + lowercase."""
    if not name:
        return ""
    return _INDUSTRY_STRIP_RE.sub("", name).lower()


def _normalize_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    s = symbol.strip().lstrip("$")
    # 大小写无关 + 去掉空格/下划线/连字符（"SK Hynix" / "SK_HYNIX" 等价）
    return _SYMBOL_STRIP_RE.sub("", s).upper()


def _from_raw(raw: dict) -> Taxonomy:
    sectors_raw = raw.get("sectors") or []
    sectors: list[Sector] = []
    for s in sectors_raw:
        industries_raw = s.get("industries") or []
        industries: list[Industry] = []
        for ind in industries_raw:
            tickers_raw = ind.get("tickers") or []
            tickers: list[TickerEntry] = []
            for t in tickers_raw:
                raw_ticker = t.get("ticker")
                if not isinstance(raw_ticker, str) or not raw_ticker.strip():
                    # YAML 1.1 把 ON/OFF/YES/NO/TRUE/FALSE/NULL 解析成 bool/None；
                    # ticker 必须显式加引号。
                    raise ValueError(
                        f"taxonomy.yaml: ticker 必须是非空字符串（实际收到 {raw_ticker!r}），"
                        f"如 ticker 撞 YAML 关键字请加引号，例如 ticker: \"ON\"。"
                    )
                also_in_raw = t.get("also_in") or ()
                also_in: list[tuple[str, str]] = []
                for loc in also_in_raw:
                    sector_name = str(loc.get("sector") or "").strip()
                    industry_name = str(loc.get("industry") or "").strip()
                    if not sector_name or not industry_name:
                        raise ValueError(
                            f"taxonomy.yaml: ticker {raw_ticker!r} 的 also_in 条目必须"
                            f"同时给出 sector 和 industry，实际收到 {loc!r}"
                        )
                    also_in.append((sector_name, industry_name))
                tickers.append(
                    TickerEntry(
                        ticker=raw_ticker,
                        company=str(t.get("company") or ""),
                        aliases=tuple(t.get("aliases") or ()),
                        notes=str(t.get("notes") or ""),
                        also_in=tuple(also_in),
                    )
                )
            industries.append(
                Industry(
                    name=str(ind["name"]),
                    description=str(ind.get("description") or ""),
                    tickers=tuple(tickers),
                )
            )
        sectors.append(
            Sector(
                name=str(s["name"]),
                description=str(s.get("description") or ""),
                industries=tuple(industries),
            )
        )

    hard = raw.get("hard_excluded") or {}
    hard_excl = HardExclusions(
        reasons=tuple(hard.get("reasons") or ()),
        sectors=tuple(hard.get("sectors") or ()),
    )
    return Taxonomy(sectors=tuple(sectors), hard_excluded=hard_excl)


@functools.lru_cache(maxsize=1)
def get_default_taxonomy() -> Taxonomy:
    """进程级缓存的默认 taxonomy；summarizer 等模块的首选入口。"""
    return Taxonomy.load()
