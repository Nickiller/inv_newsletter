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
    exclude_keywords: list[str] = field(default_factory=list)


@dataclass
class SummarizationConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    output_dir: Path = field(default_factory=lambda: Path("output/daily"))
    sectors: list[str] = field(default_factory=list)
    lark_folder_token: str | None = None
    wiki_sync_dir: Path | None = None
    weekly_wiki_sync_dir: Path | None = None


@dataclass
class MonitorConfig:
    start_hour: int = 20
    deadline_hour: int = 23
    weekday_min_sources: int = 2
    weekend_min_sources: int = 1
    grace_minutes: int = 45
    timezone: str = "Asia/Shanghai"


@dataclass
class SocialAccountConfig:
    handle: str
    name: str


@dataclass
class TwitterConfig:
    enabled: bool = False
    accounts: list[SocialAccountConfig] = field(default_factory=list)
    hours_back: int | None = None
    include_replies: bool = False
    include_retweets: bool = False


@dataclass
class TruthSocialConfig:
    enabled: bool = False
    accounts: list[SocialAccountConfig] = field(default_factory=list)
    hours_back: int | None = None


@dataclass
class SocialConfig:
    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    truth_social: TruthSocialConfig = field(default_factory=TruthSocialConfig)


@dataclass
class AppConfig:
    hours_back: int
    filters: list[FilterGroup]
    weekly_filters: list[FilterGroup] = field(default_factory=list)
    data_dir: Path = field(default_factory=lambda: Path("data/mail"))
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    social: SocialConfig = field(default_factory=SocialConfig)

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

    @property
    def all_exclude_keywords(self) -> list[str]:
        seen = set()
        result = []
        for fg in self.filters:
            for k in fg.exclude_keywords:
                if k not in seen:
                    seen.add(k)
                    result.append(k)
        return result


def email_matches_group(subject: str, sender_address: str, group: FilterGroup) -> bool:
    """A FilterGroup accepts an email when:
    - sender_address ∈ group.senders (case-insensitive exact match)
    - group.keywords empty OR ≥1 keyword is substring of subject (case-insensitive)
    - none of group.exclude_keywords appear in subject
    """
    sender_l = sender_address.lower()
    if sender_l not in {s.lower() for s in group.senders}:
        return False
    subj_l = subject.lower()
    if group.keywords and not any(k.lower() in subj_l for k in group.keywords):
        return False
    if group.exclude_keywords and any(k.lower() in subj_l for k in group.exclude_keywords):
        return False
    return True


def email_matches_any_group(subject: str, sender_address: str, groups: list[FilterGroup]) -> bool:
    return any(email_matches_group(subject, sender_address, g) for g in groups)


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
            exclude_keywords=item.get("exclude_keywords", []),
        ))

    if not filters:
        raise ValueError("No filters defined in config file.")

    weekly_filters = []
    for item in raw.get("weekly_filters", []) or []:
        weekly_filters.append(FilterGroup(
            name=item["name"],
            senders=item.get("senders", []),
            keywords=item.get("keywords", []),
            exclude_keywords=item.get("exclude_keywords", []),
        ))

    # Parse summarization config
    sum_raw = raw.get("summarization", {})
    sum_config = SummarizationConfig(
        model=sum_raw.get("model", "claude-sonnet-4-20250514"),
        max_tokens=sum_raw.get("max_tokens", 8192),
        output_dir=Path(sum_raw.get("output_dir", "output/daily")),
        sectors=sum_raw.get("sectors", []),
        lark_folder_token=sum_raw.get("lark_folder_token"),
        wiki_sync_dir=Path(sum_raw["wiki_sync_dir"]) if sum_raw.get("wiki_sync_dir") else None,
        weekly_wiki_sync_dir=Path(sum_raw["weekly_wiki_sync_dir"]) if sum_raw.get("weekly_wiki_sync_dir") else None,
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

    # Parse social config
    social_raw = raw.get("social", {})
    tw_raw = social_raw.get("twitter", {})
    ts_raw = social_raw.get("truth_social", {})
    twitter_config = TwitterConfig(
        enabled=tw_raw.get("enabled", False),
        accounts=[SocialAccountConfig(**a) for a in tw_raw.get("accounts", [])],
        hours_back=tw_raw.get("hours_back"),
        include_replies=tw_raw.get("include_replies", False),
        include_retweets=tw_raw.get("include_retweets", False),
    )
    truth_social_config = TruthSocialConfig(
        enabled=ts_raw.get("enabled", False),
        accounts=[SocialAccountConfig(**a) for a in ts_raw.get("accounts", [])],
        hours_back=ts_raw.get("hours_back"),
    )
    social_config = SocialConfig(twitter=twitter_config, truth_social=truth_social_config)

    config = AppConfig(
        hours_back=raw.get("hours_back", 24),
        filters=filters,
        weekly_filters=weekly_filters,
        summarization=sum_config,
        monitor=monitor_config,
        social=social_config,
    )
    logger.info(
        f"Loaded {len(filters)} daily + {len(weekly_filters)} weekly filter groups, "
        f"{len(config.all_senders)} unique daily senders."
    )
    return config
