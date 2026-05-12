"""Prompt composition utilities — loads the decomposed prompt files
(digest_contract, writing_style, evidence_rules, sector_prompts/*) and the
sector list from filters.yaml as the single source of truth.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SECTOR_PROMPTS_DIR = _PROMPTS_DIR / "sector_prompts"

# Map sector display name (from filters.yaml) → sector_prompts filename stem
SECTOR_PROMPT_MAP = {
    "AI 模型与平台": "ai_platform",
    "宏观与市场": "macro",
    "半导体与硬件": "semi_hardware",
    "互联网与数字广告": "internet",
    "软件与SaaS": "software_saas",
    "网络安全": "security",
    "其他": "other",
}


def load_sectors(filters_yaml_path: Path) -> list[str]:
    """Read sector list from filters.yaml as single source of truth.

    Falls back to SECTOR_PROMPT_MAP keys if the yaml is missing the field.
    """
    if filters_yaml_path.exists():
        data = yaml.safe_load(filters_yaml_path.read_text(encoding="utf-8")) or {}
        sectors = data.get("summarization", {}).get("sectors")
        if sectors:
            return sectors
    return list(SECTOR_PROMPT_MAP.keys())


def load_contract() -> str:
    return (_PROMPTS_DIR / "digest_contract.md").read_text(encoding="utf-8")


def load_writing_style() -> str:
    return (_PROMPTS_DIR / "writing_style.md").read_text(encoding="utf-8")


def load_evidence_rules() -> str:
    return (_PROMPTS_DIR / "evidence_rules.md").read_text(encoding="utf-8")


def load_sector_prompt(sector_name: str) -> str:
    stem = SECTOR_PROMPT_MAP.get(sector_name)
    if not stem:
        return f"# Sector Prompt — {sector_name}\n\n(No specialized prompt; use general contract.)\n"
    path = _SECTOR_PROMPTS_DIR / f"{stem}.md"
    if not path.exists():
        return f"# Sector Prompt — {sector_name}\n\n(Missing file: {path.name})\n"
    return path.read_text(encoding="utf-8")
