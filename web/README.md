# Daily Digest Web UI

Next.js reading view for `inv_newsletter` daily digests with sector / ticker filtering.

## Prerequisites

- Node >= 20
- `inv_newsletter` has produced at least one `output/daily/YYYY-MM-DD_daily_digest.md` file (the parent repo's `output/daily/` is read by default).

## Run

```bash
cd web
npm install         # first time only
npm run dev         # http://localhost:3000
```

By default the app reads from `../output/daily` (relative to `web/`). Override with:

```bash
INV_OUTPUT_DIR=/abs/path/to/output/daily npm run dev
```

## Routes

| Path | What |
|---|---|
| `/` | Date list (descending), with sector/ticker counts |
| `/digest/[date]` | Filtered digest view |
| `/api/image/[date]/[file]` | Image proxy from `output/daily/{date}/{file}` |

Filter state is encoded in the URL as `?sectors=A,B&tickers=AAPL,META`.

## Build

```bash
npm run build
npm run start
```
