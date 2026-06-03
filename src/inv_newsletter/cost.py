"""Token-usage accounting and cost estimation for summarizer runs.

`_run_usage` is a module-level accumulator: callers reset it with `.clear()` at
the start of a run and append per-call usage dicts. It is mutated in place only
(never rebound), so importing the name elsewhere shares the same list object.
"""

# Per-million-token USD prices (Anthropic public pricing). Update if pricing changes.
_PRICE_PER_MTOK = {
    "opus":   (15.00, 75.00),
    "sonnet": (3.00, 15.00),
    "haiku":  (1.00,  5.00),
}
_run_usage: list[dict] = []  # accumulated per summarize_daily run; reset at function entry


def _price_tier(model: str) -> str | None:
    m = model.lower()
    for tier in _PRICE_PER_MTOK:
        if tier in m:
            return tier
    return None


def _record_usage(model: str, usage) -> None:
    _run_usage.append({
        "model": model,
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    })


def _estimate_tokens_from_text(text: str) -> int:
    # Fallback for proxies that don't relay the streaming message_delta event,
    # leaving final.usage.output_tokens=0. ~4 ASCII chars/token, ~1 token/CJK char.
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return int(ascii_n / 4 + (len(text) - ascii_n))


def _format_cost_report() -> str:
    if not _run_usage:
        return ""
    by_model: dict[str, dict] = {}
    for r in _run_usage:
        e = by_model.setdefault(r["model"], {"calls": 0, "in": 0, "out": 0, "cwrite": 0, "cread": 0})
        e["calls"] += 1
        e["in"] += r["input_tokens"]
        e["out"] += r["output_tokens"]
        e["cwrite"] += r["cache_creation_input_tokens"]
        e["cread"] += r["cache_read_input_tokens"]
    lines = ["", "=" * 70, "💰 本次运行 token 用量与估算费用", "=" * 70]
    total = 0.0
    unknown: list[str] = []
    for model, e in by_model.items():
        tier = _price_tier(model)
        if tier is None:
            unknown.append(model)
            cost_str = "N/A"
            cache_str = ""
        else:
            in_p, out_p = _PRICE_PER_MTOK[tier]
            # Anthropic cache pricing: write = 1.25x input, read = 0.1x input
            cost = (
                e["in"] / 1_000_000 * in_p
                + e["out"] / 1_000_000 * out_p
                + e["cwrite"] / 1_000_000 * in_p * 1.25
                + e["cread"] / 1_000_000 * in_p * 0.1
            )
            total += cost
            cost_str = f"${cost:.4f}"
            cache_str = f", cache w/r {e['cwrite']:,}/{e['cread']:,}" if (e["cwrite"] or e["cread"]) else ""
        lines.append(
            f"  {model}: {e['calls']} 调用, "
            f"in {e['in']:,} / out {e['out']:,} tokens{cache_str} → {cost_str}"
        )
    lines.append("-" * 70)
    suffix = f"  (未识别模型: {', '.join(unknown)})" if unknown else ""
    lines.append(f"  总计: ${total:.4f}{suffix}")
    lines.append("=" * 70)
    return "\n".join(lines)
