import { promises as fs } from "node:fs";
import path from "node:path";
import { parseDigest, type Digest } from "./parser";

// Default points at <repo>/output/daily, where the inv_newsletter CLI writes.
// `cwd()` here is `<repo>/web` when running `next dev`.
const DEFAULT_DIR = path.resolve(process.cwd(), "..", "output", "daily");

export function getOutputDir(): string {
  return process.env.INV_OUTPUT_DIR
    ? path.resolve(process.env.INV_OUTPUT_DIR)
    : DEFAULT_DIR;
}

const DIGEST_FILE_RE = /^(\d{4}-\d{2}-\d{2})_daily_digest(?:_v\d+)?\.md$/;

export type DigestSummary = {
  date: string; // YYYY-MM-DD
  filename: string; // basename
  intro: string; // first non-empty line after the title (used as preview)
  sectorCount: number;
  tickerCount: number;
};

export async function listDigests(): Promise<DigestSummary[]> {
  const dir = getOutputDir();
  let entries: string[];
  try {
    entries = await fs.readdir(dir);
  } catch {
    return [];
  }

  // If multiple files share a date (e.g., _v2), prefer the lexicographically
  // largest filename (so _v2 > base).
  const byDate = new Map<string, string>();
  for (const name of entries) {
    const m = name.match(DIGEST_FILE_RE);
    if (!m) continue;
    const date = m[1];
    const prev = byDate.get(date);
    if (!prev || name > prev) byDate.set(date, name);
  }

  const dates = Array.from(byDate.keys()).sort().reverse();
  const out: DigestSummary[] = [];
  for (const date of dates) {
    const filename = byDate.get(date)!;
    try {
      const raw = await fs.readFile(path.join(dir, filename), "utf-8");
      const digest = parseDigest(date, raw);
      const tickers = new Set<string>();
      for (const sec of digest.sectors)
        for (const sub of sec.subsections)
          for (const t of sub.allTickers) tickers.add(t);

      out.push({
        date,
        filename,
        intro: firstParagraph(digest.intro),
        sectorCount: digest.sectors.length,
        tickerCount: tickers.size,
      });
    } catch {
      // skip unreadable files
    }
  }
  return out;
}

export async function loadDigest(date: string): Promise<Digest | null> {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const dir = getOutputDir();
  let entries: string[];
  try {
    entries = await fs.readdir(dir);
  } catch {
    return null;
  }
  const candidates = entries
    .filter((n) => {
      const m = n.match(DIGEST_FILE_RE);
      return m !== null && m[1] === date;
    })
    .sort()
    .reverse();
  if (candidates.length === 0) return null;
  const raw = await fs.readFile(path.join(dir, candidates[0]), "utf-8");
  return parseDigest(date, raw);
}

function firstParagraph(intro: string): string {
  // Skip the H1 title, return the first non-empty subsequent line, stripped of
  // markdown blockquote markers.
  const lines = intro.split(/\r?\n/);
  for (const ln of lines) {
    const t = ln.replace(/^>\s*/, "").trim();
    if (!t) continue;
    if (t.startsWith("#")) continue;
    return t;
  }
  return "";
}
