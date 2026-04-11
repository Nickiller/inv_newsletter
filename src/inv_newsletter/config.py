"""Load and validate filters.yaml configuration."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class FilterGroup:
    name: str
    senders: list[str]
    keywords: list[str] = field(default_factory=list)


@dataclass
class SummarizationConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    output_dir: Path = field(default_factory=lambda: Path("output/daily"))
    sectors: list[str] = field(default_factory=list)
    lark_folder_token: str | None = None


@dataclass
class MonitorConfig:
    start_hour: int = 20
    deadline_hour: int = 23
    weekday_min_sources: int = 2
    weekend_min_sources: int = 1
    grace_minutes: int = 45
    timezone: str = "Asia/Shanghai"


@dataclass
class AppConfig:
    hours_back: int
    filters: list[FilterGroup]
    data_dir: Path = field(default_factory=lambda: Path("data/mail"))
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)

    @property
    def all_senders(self) -> list[str]:
        seen = set()
        result = []
        for fg in self.filters:
            for s in fg.senders:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
        return result

    @property
    def all_keywords(self) -> list[str]:
        seen = set()
        result = []
        for fg in self.filters:
            for k in fg.keywords:
                if k not in seen:
                    seen.add(k)
                    result.append(k)
        return result


def load_config(path: Path | None = None) -> AppConfig:
    """Load filters.yaml from the given path or default locations."""
    if path is None:
        path = Path("filters.yaml")

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    filters = []
    for item in raw.get("filters", []):
        filters.append(FilterGroup(
            name=item["name"],
            senders=item.get("senders", []),
            keywords=item.get("keywords", []),
        ))

    if not filters:
        raise ValueError("No filters defined in config file.")

    # Parse summarization config
    sum_raw = raw.get("summarization", {})
    sum_config = SummarizationConfig(
        model=sum_raw.get("model", "claude-sonnet-4-20250514"),
        max_tokens=sum_raw.get("max_tokens", 8192),
        output_dir=Path(sum_raw.get("output_dir", "output/daily")),
        sectors=sum_raw.get("sectors", []),
        lark_folder_token=sum_raw.get("lark_folder_token"),
    )

    # Parse monitor config
    mon_raw = raw.get("monitor", {})
    monitor_config = MonitorConfig(
        start_hour=mon_raw.get("start_hour", 20),
        deadline_hour=mon_raw.get("deadline_hour", 23),
        weekday_min_sources=mon_raw.get("weekday_min_sources", 2),
        weekend_min_sources=mon_raw.get("weekend_min_sources", 1),
        grace_minutes=mon_raw.get("grace_minutes", 45),
        timezone=mon_raw.get("timezone", "Asia/Shanghai"),
    )

    config = AppConfig(
        hours_back=raw.get("hours_back", 24),
        filters=filters,
        summarization=sum_config,
        monitor=monitor_config,
    )
    logger.info(f"Loaded {len(filters)} filter groups, {len(config.all_senders)} unique senders.")
    return config
