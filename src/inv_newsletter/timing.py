"""Per-run CPU vs LLM timing telemetry.

Module-level singleton: CLI calls start_run() at entry and flush() at exit;
sub-modules grab the timer via get_timer() and use phase()/record_llm_call().

When start_run() was never called, get_timer() returns a no-op stub so
sub-modules don't have to branch.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TELEMETRY_PATH = Path("data/run_telemetry.jsonl")


class _NoopTimer:
    @contextmanager
    def phase(self, name: str, kind: str = "cpu"):
        yield

    def record_llm_call(self, *args, **kwargs):
        pass


class RunTimer:
    def __init__(self, command: str, extra: dict):
        self.command = command
        self.extra = extra
        self.started_at = time.perf_counter()
        self.started_ts = datetime.now().astimezone().isoformat(timespec="seconds")
        self.phases: list[dict] = []

    @contextmanager
    def phase(self, name: str, kind: str = "cpu"):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.phases.append({
                "name": name,
                "kind": kind,
                "sec": round(time.perf_counter() - t0, 3),
            })

    def record_llm_call(
        self,
        name: str,
        model: str,
        duration_sec: float,
        tokens_in: int,
        tokens_out: int,
        stop_reason: str | None = None,
        calls: int = 1,
    ) -> None:
        entry = {
            "name": name,
            "kind": "llm",
            "sec": round(duration_sec, 3),
            "calls": calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
        }
        if stop_reason is not None:
            entry["stop_reason"] = stop_reason
        self.phases.append(entry)


_TIMER: RunTimer | None = None
_NOOP = _NoopTimer()


def start_run(command: str, **extra) -> None:
    global _TIMER
    _TIMER = RunTimer(command, extra)


def get_timer():
    return _TIMER if _TIMER is not None else _NOOP


def flush(path: Path = DEFAULT_TELEMETRY_PATH) -> None:
    """Write current run as one JSON line and print a stdout summary. Resets state."""
    global _TIMER
    if _TIMER is None:
        return
    timer = _TIMER
    _TIMER = None  # reset before any IO so a crash doesn't leave a half-state

    wall_total = round(time.perf_counter() - timer.started_at, 3)
    cpu_sec = round(sum(p["sec"] for p in timer.phases if p["kind"] == "cpu"), 3)
    llm_sec = round(sum(p["sec"] for p in timer.phases if p["kind"] == "llm"), 3)

    record = {
        "ts": timer.started_ts,
        "command": timer.command,
        "wall_total_sec": wall_total,
        "cpu_sec": cpu_sec,
        "llm_sec": llm_sec,
        "phases": timer.phases,
        **timer.extra,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write run telemetry to {path}: {e}")

    _print_summary(record)


def _fmt_tok(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _bar(frac: float, width: int) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return "█" * filled + "░" * (width - filled)


def _print_summary(record: dict) -> None:
    wall = record["wall_total_sec"]
    cpu = record["cpu_sec"]
    llm = record["llm_sec"]
    cpu_pct = round(cpu / wall * 100) if wall else 0
    llm_pct = round(llm / wall * 100) if wall else 0

    rule = "═" * 62
    cmd = record.get("command", "")
    date_part = record.get("target_date") or ""
    header_pieces = [p for p in ["⏱  inv-newsletter timing", cmd, date_part] if p]

    print()
    print(rule)
    print("  " + "  ·  ".join(header_pieces))
    print(rule)
    print(f"  Total      {wall:>6.1f}s")
    print(f"  CPU        {cpu:>6.1f}s  ▕{_bar(cpu / wall if wall else 0, 30)}▏  {cpu_pct:>3}%")
    print(f"  LLM        {llm:>6.1f}s  ▕{_bar(llm / wall if wall else 0, 30)}▏  {llm_pct:>3}%")

    cpu_phases = sorted([p for p in record["phases"] if p["kind"] == "cpu"], key=lambda p: -p["sec"])
    llm_phases = [p for p in record["phases"] if p["kind"] == "llm"]

    if cpu_phases and cpu > 0:
        print()
        print(f"  CPU phases{' ' * 42}(of CPU)")
        print("  " + "─" * 60)
        for p in cpu_phases:
            pct = round(p["sec"] / cpu * 100) if cpu else 0
            print(f"    {p['name']:<16} {p['sec']:>6.1f}s   {_bar(p['sec'] / cpu if cpu else 0, 16)}   {pct:>3}%")

    if llm_phases and llm > 0:
        print()
        print(f"  LLM phases{' ' * 42}(of LLM)")
        print("  " + "─" * 60)
        for p in llm_phases:
            pct = round(p["sec"] / llm * 100) if llm else 0
            model_short = p["model"].replace("claude-", "").replace("-20251001", "")
            extras = []
            if p["calls"] != 1:
                extras.append(f"{p['calls']} calls")
            extras.append(model_short)
            extras.append(f"{_fmt_tok(p['tokens_in'])} → {_fmt_tok(p['tokens_out'])} tok")
            stop = p.get("stop_reason")
            if stop and stop != "end_turn":
                extras.append(f"stop={stop}")
            print(f"    {p['name']:<16} {p['sec']:>6.1f}s   {_bar(p['sec'] / llm if llm else 0, 16)}   {pct:>3}%")
            print(f"      {' · '.join(extras)}")

    print(rule)
