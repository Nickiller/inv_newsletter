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
class AppConfig:
    hours_back: int
    filters: list[FilterGroup]
    data_dir: Path = field(default_factory=lambda: Path("data/mail"))

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

    config = AppConfig(
        hours_back=raw.get("hours_back", 24),
        filters=filters,
    )
    logger.info(f"Loaded {len(filters)} filter groups, {len(config.all_senders)} unique senders.")
    return config
