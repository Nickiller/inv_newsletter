#!/usr/bin/env python3
"""Drive the full digest_v3 pipeline end-to-end for one date.

Deterministic stages (chunk / route_merge / assemble / finalize) shell out to the
existing module CLIs. LLM stages (format / route / sections / catalyst / tldr) are
driven here via a thin Anthropic client — same proxy/client as the legacy path.

Stages are idempotent and individually re-runnable; pass --from <stage> to resume.

    .venv/bin/python scripts/run_v3.py --date 2026-06-08
    .venv/bin/python scripts/run_v3.py --date 2026-06-08 --from sections

Default model is sonnet (cheap, proxy-confirmed). Use the SAME model family as the
legacy run so the v3-vs-legacy comparison isolates architecture, not model tier.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
load_dotenv(REPO / ".env", override=True)

import anthropic  # noqa: E402
from inv_newsletter.tldr import generate_tldr  # noqa: E402

PROMPTS = REPO / "src" / "inv_newsletter" / "digest_v3" / "prompts"
SECTION_PROMPTS = PROMPTS / "sections"
MASTER_PROMPT = PROMPTS / "master.md"

STAGES = ["format", "chunk", "route", "route_merge", "sections", "catalyst",
          "assemble", "tldr", "finalize"]

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        import os
        _client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )
    return _client


def _strip_fence(t: str) -> str:
    t = t.strip()
    t = re.sub(r"^```(?:json|markdown)?\s*\n?", "", t)
    t = re.sub(r"\n?```\s*$", "", t)
    return t.strip()


def llm(system: str, user: str, model: str, max_tokens: int = 12000) -> tuple[str, dict]:
    t0 = time.perf_counter()
    chunks: list[str] = []
    with client().messages.stream(
        model=model, max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for txt in stream.text_stream:
            chunks.append(txt)
        final = stream.get_final_message()
    usage = {"in": final.usage.input_tokens, "out": final.usage.output_tokens,
             "sec": time.perf_counter() - t0, "stop": final.stop_reason}
    return _strip_fence("".join(chunks)), usage


def sh(args: list[str]) -> None:
    """Run a deterministic module CLI in the repo venv."""
    print(f"   $ {' '.join(args)}", flush=True)
    r = subprocess.run([sys.executable, *args], cwd=REPO,
                       capture_output=True, text=True)
    if r.stdout.strip():
        print("   " + r.stdout.strip().replace("\n", "\n   "), flush=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"stage failed: {' '.join(args)}")


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


def _v3(date: str) -> Path:
    return REPO / "output" / "daily" / date / "v3"


def _email_slugs(date: str) -> list[str]:
    mail = REPO / "data" / "mail" / date
    return sorted(p.name for p in mail.iterdir() if p.is_dir())


def _extract_json_array(text: str) -> list:
    text = _strip_fence(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("["), text.rfind("]")
        if i >= 0 and j > i:
            return json.loads(text[i:j + 1])
        raise


# ── stages ───────────────────────────────────────────────────────────────
def stage_format(date: str, model: str) -> None:
    out = _v3(date) / "formatted"
    out.mkdir(parents=True, exist_ok=True)
    for slug in _email_slugs(date):
        em = REPO / "data" / "mail" / date / slug / "email.md"
        if not em.exists():
            print(f"   skip {slug} (no email.md)", flush=True)
            continue
        body = _strip_frontmatter(em.read_text(encoding="utf-8"))
        md, u = llm(MASTER_PROMPT.parent.joinpath("format.md").read_text("utf-8"),
                    body, model, max_tokens=16000)
        (out / f"{slug}.md").write_text(md.rstrip() + "\n", encoding="utf-8")
        print(f"   ✓ format {slug}  ({u['out']} tok, {u['sec']:.0f}s)", flush=True)


def stage_route(date: str, model: str) -> None:
    cbe = _v3(date) / "chunks_by_email"
    out = _v3(date) / "routes"
    out.mkdir(parents=True, exist_ok=True)
    route_prompt = (PROMPTS / "route.md").read_text("utf-8")
    for fp in sorted(cbe.glob("*.json")):
        slug = fp.stem
        user = (fp.read_text("utf-8") +
                "\n\n上方是本封邮件的 chunk 列表。请按 system prompt 路由，"
                "**输出一个 JSON 数组**，每个元素对应一个 chunk 的路由对象（含 chunk_id / routes / catalysts），"
                "严格 JSON、无代码围栏、无多余文字。")
        raw, u = llm(route_prompt, user, model, max_tokens=8000)
        arr = _extract_json_array(raw)
        (out / f"{slug}.json").write_text(
            json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"   ✓ route {slug}  ({len(arr)} chunks, {u['out']} tok, {u['sec']:.0f}s)", flush=True)


def stage_sections(date: str, model: str) -> None:
    si = _v3(date) / "sections_input"
    out = _v3(date) / "sections"
    out.mkdir(parents=True, exist_ok=True)
    master = MASTER_PROMPT.read_text("utf-8")
    for fp in sorted(si.glob("*.json")):
        slug = fp.stem
        dest = out / f"{slug}.md"
        if dest.exists() and dest.stat().st_size > 200:
            print(f"   ✓ section {slug} (cached, skipping)", flush=True)
            continue
        sp = SECTION_PROMPTS / f"{slug}.md"
        system = master + "\n\n" + (sp.read_text("utf-8") if sp.exists() else "")
        md, u = llm(system, fp.read_text("utf-8"), model, max_tokens=12000)
        dest.write_text(md.rstrip() + "\n", encoding="utf-8")
        print(f"   ✓ section {slug}  ({u['out']} tok, {u['sec']:.0f}s)", flush=True)


def stage_catalyst(date: str, model: str) -> None:
    routes_dir = _v3(date) / "routes"
    cats: list = []
    for fp in sorted(routes_dir.glob("*.json")):
        for obj in json.loads(fp.read_text("utf-8")):
            for c in obj.get("catalysts") or []:
                cats.append(c)
    if not cats:
        print("   (no catalysts) — skipping", flush=True)
        return
    md, u = llm((PROMPTS / "catalyst.md").read_text("utf-8"),
                json.dumps(cats, ensure_ascii=False, indent=2), model, max_tokens=4000)
    (_v3(date) / "catalyst.md").write_text(md.rstrip() + "\n", encoding="utf-8")
    print(f"   ✓ catalyst ({len(cats)} raw events, {u['out']} tok, {u['sec']:.0f}s)", flush=True)


def stage_tldr(date: str, model: str) -> None:
    body = (_v3(date) / "body.md").read_text("utf-8")
    text, usage = generate_tldr(body, model=model)
    (_v3(date) / "tldr.md").write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"   ✓ tldr ({usage['output_tokens']} tok, {usage['duration_sec']:.0f}s)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--from", dest="from_stage", default="format", choices=STAGES)
    args = ap.parse_args()
    date, model = args.date, args.model
    start = STAGES.index(args.from_stage)

    print(f"▶ digest_v3 pipeline · {date} · model={model} · from={args.from_stage}\n", flush=True)
    t0 = time.perf_counter()
    for stage in STAGES[start:]:
        print(f"━━ {stage} ━━", flush=True)
        if stage == "format":
            stage_format(date, model)
        elif stage == "chunk":
            sh(["-m", "inv_newsletter.digest_v3.chunk", date])
        elif stage == "route":
            stage_route(date, model)
        elif stage == "route_merge":
            sh(["-m", "inv_newsletter.digest_v3.route_merge", date])
        elif stage == "sections":
            stage_sections(date, model)
        elif stage == "catalyst":
            stage_catalyst(date, model)
        elif stage == "assemble":
            sh(["-m", "inv_newsletter.digest_v3.assemble", "assemble", date])
        elif stage == "tldr":
            stage_tldr(date, model)
        elif stage == "finalize":
            sh(["-m", "inv_newsletter.digest_v3.assemble", "finalize", date])
        print(flush=True)

    out = REPO / "output" / "daily" / f"{date}_daily_digest_v3.md"
    print(f"✅ done in {time.perf_counter()-t0:.0f}s → {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
