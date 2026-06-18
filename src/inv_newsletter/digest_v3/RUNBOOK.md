# digest_v3 — Orchestration Runbook (CC-subagent driven)

How a Claude Code session drives the full v3 digest pipeline for one `<date>`
(`YYYY-MM-DD`). v3 has **no API harness by design** — deterministic stages are
`python -m` CLIs, every LLM stage runs as a CC subagent. This file is the
*orchestration spec* (audience: the driving session). It **references** the
stage prompts; it never restates their writing rules.

- Prompts live in `src/inv_newsletter/digest_v3/prompts/` (and `tldr.md` in
  `src/inv_newsletter/prompts/`). Subagents `Read` their own prompt file — do
  not paste prompt bodies into subagent instructions, just point at the path.
- `master.md` is the **sections-stage prompt** (writing rules for one `## 板块`).
  It is fed to the section subagents only; it is not part of this runbook's job.
- All paths below are relative to the repo root
  `/Users/zhangxypro/Code/Claude_Workspace/inv_newsletter`.

## Preconditions

- Emails already fetched to `data/mail/<date>/<slug>/email.md` (+ images). The
  caller (scheduled `SKILL.md`) does the `git checkout main` + fetch first.
- venv at `.venv/`. The deterministic CLIs make no network calls. Subagents are
  CC agents (no `ANTHROPIC_API_KEY` needed). Only the **legacy fallback** and the
  publish step touch external services.

## Models per stage

| stage | driver | model |
|---|---|---|
| format | subagent ×N (one per email) | sonnet |
| chunk | `python -m` CLI | — |
| text-route | subagent ×N (one per email) | sonnet |
| image-route | subagent ×M (emails that have images) | sonnet (vision) |
| route_merge | `python -m` CLI | — |
| sections | subagent ×K (sectors with content) | **opus** |
| catalyst | subagent ×1 | sonnet |
| assemble | `python -m` CLI | — |
| tldr | subagent ×1 | **opus** |
| finalize | `python -m` CLI | — |

Fan out same-stage subagents in **one message** (parallel). Each subagent
`Write`s its own output file and returns a one-line status only (keep the
driver's context clean).

## Sector slug ↔ name

`ai_platform`=AI 模型与平台 · `macro`=宏观与市场 · `semi_hardware`=半导体与硬件 ·
`internet`=互联网与数字广告 · `software_saas`=软件与SaaS · `other`=其他

---

## Stage 1 — format (subagent ×N, sonnet)

`mkdir -p output/daily/<date>/v3/formatted`. List slugs:
`ls -1 data/mail/<date>/` (each dir with an `email.md`).

Per slug, one subagent: `Read` prompt `digest_v3/prompts/format.md` + `Read`
`data/mail/<date>/<slug>/email.md` (ignore YAML frontmatter, process body) →
`Write` `output/daily/<date>/v3/formatted/<slug>.md`. Status: `format OK <slug>`.

## Stage 2 — chunk (CLI)

```
.venv/bin/python -m inv_newsletter.digest_v3.chunk <date>
```
Writes `v3/chunks.json` + `v3/chunks_by_email/<slug>.json`. Image chunks get
`IMG_NN` ids + `image_path`, empty caption (filled at image-route).

## Stage 3 — text-route (subagent ×N, sonnet)

`mkdir -p output/daily/<date>/v3/routes`. Per slug, one subagent: `Read` prompt
`digest_v3/prompts/route.md` + `Read` `v3/chunks_by_email/<slug>.json` → build a
**JSON array**, one route object per chunk (`{chunk_id, routes, catalysts}` per
route.md `<output>`) → `Write` `v3/routes/<slug>.json` (strict JSON, no fences).
Status: `route OK <slug> — N chunks`.

## Stage 4 — image-route (subagent ×M, sonnet, vision)

`mkdir -p output/daily/<date>/v3/image_routes`. Derive the per-email image
manifest from `chunks.json`:

```
.venv/bin/python - <<'PY'
import json
from collections import defaultdict
d=json.load(open("output/daily/<date>/v3/chunks.json"))
imgs=defaultdict(list)
for c in d["chunks"]:
    if c.get("type")=="image":
        imgs[c["source_slug"]].append((c["chunk_id"], c["image_path"]))
for slug,lst in imgs.items():
    print(f"### {slug}")
    for cid,p in lst: print(f"{cid}\t{p}")
PY
```

For each slug that has images, one subagent: `Read` prompt
`digest_v3/prompts/image_route.md`, then **actually `Read` each image file**
(vision — do not guess from filename), → **JSON array** of
`{img_id, caption, primary, tickers}` (img_id = the `IMG_NN` above, one per
image, in order) → `Write` `v3/image_routes/<slug>.json`. Status:
`image-route OK <slug> — X routed / Y DROP`.

## Stage 5 — route_merge (CLI)

```
.venv/bin/python -m inv_newsletter.digest_v3.route_merge <date>
```
Writes `v3/route_map.json` (+ code-computed `multi_source` / `theme_multi_source`
/ merged `catalysts`) and `v3/sections_input/<slug>.json` (one per non-empty
sector; primary already importance-sorted). Print the `stats` block for sanity.

## Stage 6 — sections (subagent ×K, opus)

`mkdir -p output/daily/<date>/v3/sections`. One subagent **per file present in**
`v3/sections_input/`. Each: `Read` `digest_v3/prompts/master.md` (overarching
rules) + `Read` `digest_v3/prompts/sections/<slug>.md` (sector prompt) + `Read`
`v3/sections_input/<slug>.json` → write the single `## <板块名>` body (primary in
given order; `headline:true` → own `#### TICKER`; `theme_multi_source:true`
items grouped, each its own bullet; embed `![cap](IMG_NN)` only from the images
list; keep all URLs; **no** TL;DR / 本周关注 / meta preamble) → `Write`
`v3/sections/<slug>.md`. Status: `section OK <slug>`.

## Stage 7 — catalyst (subagent ×1, sonnet)

One subagent: `Read` `digest_v3/prompts/catalyst.md` + `Read` the `catalysts`
array from `v3/route_map.json` → `Write` `v3/catalyst.md` (`## 本周关注` only;
empty file if no events). Status: `catalyst OK — N events`.

## Stage 8 — assemble (CLI)

```
.venv/bin/python -m inv_newsletter.digest_v3.assemble assemble <date>
```
Concatenates section drafts, enforces canonical order, appends `catalyst.md`,
validates + embeds `IMG_NN` → `v3/body.md`.

## Stage 9 — tldr (subagent ×1, opus)

One subagent: `Read` `src/inv_newsletter/prompts/tldr.md` (note: main prompts
dir, **not** digest_v3) + `Read` `v3/body.md` (treat as the `<digest>` body) →
extract `## 今日要点` (3–5 bullets, reuse only links already in body) → `Write`
`v3/tldr.md`. Status: `tldr OK — N bullets`.

## Stage 10 — finalize (CLI)

```
.venv/bin/python -m inv_newsletter.digest_v3.assemble finalize <date>
```
Prepends TL;DR → `output/daily/<date>_daily_digest_v3.md` (the published file).

---

## Post: de-AI sweep + publish

1. **Leaked-tag sweep** (the section stage occasionally prints internal flags):
   ```
   grep -nE 'multi_source|theme_multi|chunk_id|primary:|headline:|DROP' output/daily/<date>_daily_digest_v3.md
   ```
   Any hit that is an internal flag (not genuine content) → strip it with a
   surgical `Edit`, preserving the surrounding sentence's meaning.
2. **Publish**:
   ```
   inv-newsletter --publish-file output/daily/<date>_daily_digest_v3.md
   ```
   Returns the Lark doc URL + the 微信分享文案. Return both to the caller.
   Publishing also refreshes `output/last_run.json` automatically (via
   `cli._write_last_run`) — the WeChat bridge reads that file to report status on
   demand (Pattern A). No separate step needed; the legacy fallback path writes
   it too.

> Optional quality pass (not yet wired): `reviewer.py` (de-AI prose rewrite,
> URL+IMG signature gate). Skip unless explicitly requested.

## Fallback

If any stage fails irrecoverably (malformed JSON a subagent can't fix on one
retry, a CLI error, etc.) and the day's digest still needs to ship, fall back to
the **legacy single-prompt path** so *a* digest goes out:
```
unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_CUSTOM_HEADERS
source .venv/bin/activate && inv-newsletter --summarize --publish --date <date>
```
Note in the run report that the fallback was used and which stage failed.

## Idempotency / resume

Every stage writes to a fixed path and can be re-run. To resume after a failure,
re-run from the failed stage onward — downstream stages overwrite cleanly. The
deterministic CLIs are pure functions of their inputs.
