"""Per-stage cost tracker. Persists to disk so partial runs can still report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Anthropic public per-million-token pricing (USD). Update if pricing changes.
_PRICE_PER_MTOK = {
    "opus":   (15.00, 75.00),
    "sonnet": (3.00, 15.00),
    "haiku":  (1.00,  5.00),
}


def _price_tier(model: str) -> str | None:
    m = model.lower()
    for tier in _PRICE_PER_MTOK:
        if tier in m:
            return tier
    return None


def _estimate_cost(model: str, in_tokens: int, out_tokens: int,
                   cache_write: int = 0, cache_read: int = 0) -> float | None:
    tier = _price_tier(model)
    if tier is None:
        return None
    in_p, out_p = _PRICE_PER_MTOK[tier]
    return (
        in_tokens / 1_000_000 * in_p
        + out_tokens / 1_000_000 * out_p
        + cache_write / 1_000_000 * in_p * 1.25
        + cache_read / 1_000_000 * in_p * 0.1
    )


class CostLedger:
    """Accumulate per-call cost entries; persist to JSON; print summary."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.entries: list[dict[str, Any]] = []

    def record(self, *, stage: str, model: str, usage: Any, duration_sec: float = 0.0,
               note: str = "") -> None:
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cread = getattr(usage, "cache_read_input_tokens", 0) or 0
        cost = _estimate_cost(model, in_tok, out_tok, cwrite, cread)
        self.entries.append({
            "stage": stage,
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_write_tokens": cwrite,
            "cache_read_tokens": cread,
            "duration_sec": round(duration_sec, 2),
            "cost_usd": round(cost, 4) if cost is not None else None,
            "note": note,
        })
        self._persist()

    def record_raw(self, *, stage: str, model: str, input_tokens: int, output_tokens: int,
                   cache_write_tokens: int = 0, cache_read_tokens: int = 0,
                   duration_sec: float = 0.0, note: str = "") -> None:
        cost = _estimate_cost(model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)
        self.entries.append({
            "stage": stage,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cache_read_tokens": cache_read_tokens,
            "duration_sec": round(duration_sec, 2),
            "cost_usd": round(cost, 4) if cost is not None else None,
            "note": note,
        })
        self._persist()

    def _persist(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": self.entries,
            "totals": self.totals(),
        }
        self.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def totals(self) -> dict[str, Any]:
        by_stage: dict[str, dict] = {}
        grand_cost = 0.0
        grand_in = 0
        grand_out = 0
        for e in self.entries:
            key = e["stage"]
            s = by_stage.setdefault(key, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "duration": 0.0})
            s["calls"] += 1
            s["in"] += e["input_tokens"]
            s["out"] += e["output_tokens"]
            s["cost"] += e["cost_usd"] or 0.0
            s["duration"] += e["duration_sec"]
            grand_cost += e["cost_usd"] or 0.0
            grand_in += e["input_tokens"]
            grand_out += e["output_tokens"]
        return {
            "by_stage": {k: {**v, "cost": round(v["cost"], 4), "duration": round(v["duration"], 2)}
                         for k, v in by_stage.items()},
            "grand_cost_usd": round(grand_cost, 4),
            "grand_input_tokens": grand_in,
            "grand_output_tokens": grand_out,
        }

    def print_summary(self) -> None:
        t = self.totals()
        lines = ["", "=" * 72, "💰 refactor_v2 pipeline cost summary", "=" * 72]
        for stage, s in t["by_stage"].items():
            lines.append(
                f"  {stage:24s} {s['calls']:2d} calls  "
                f"in {s['in']:>8,} / out {s['out']:>6,}  "
                f"{s['duration']:>5.1f}s  ${s['cost']:.4f}"
            )
        lines.append("-" * 72)
        lines.append(f"  {'TOTAL':24s}              "
                     f"in {t['grand_input_tokens']:>8,} / out {t['grand_output_tokens']:>6,}  "
                     f"            ${t['grand_cost_usd']:.4f}")
        lines.append("=" * 72)
        print("\n".join(lines))
