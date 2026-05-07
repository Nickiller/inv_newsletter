import {
  CALENDAR_HEADING_MARKER,
  MAX_TICKER_LEN,
  MIN_TICKER_LEN,
  SECTOR_ORDER,
  TICKER_NOISE,
  type SectorName,
} from "./constants";

export type Subsection = {
  id: string; // slugified heading, used for anchors and React keys
  heading: string; // raw heading text without the "### " prefix
  primaryTicker: string | null;
  allTickers: string[];
  bodyMd: string;
};

export type Sector = {
  name: SectorName | string;
  subsections: Subsection[];
};

export type Digest = {
  date: string; // YYYY-MM-DD
  intro: string; // markdown above the first ## heading
  sectors: Sector[];
  calendar: string | null; // markdown of the "📅 本周关注催化剂" section
};

const TICKER_RE = new RegExp(
  `\\b([A-Z]{${MIN_TICKER_LEN},${MAX_TICKER_LEN}})\\b`,
  "g"
);

function extractTickers(heading: string): {
  primary: string | null;
  all: string[];
} {
  const found = new Set<string>();
  let primary: string | null = null;

  // 1) Leading ticker: "AAPL (Apple)" or "META (META) — RIF..."
  const leading = heading.match(/^([A-Z]{2,5})\b/);
  if (leading && !TICKER_NOISE.has(leading[1])) {
    primary = leading[1];
    found.add(leading[1]);
  }

  // 2) Parenthetical: "Mastercard (MA) Q126 ..." — only accept tokens that
  // are already all-uppercase in the source (so "(Apple)" / "(Roblox)" don't
  // become fake tickers).
  const parens = heading.matchAll(/\(([^)]+)\)/g);
  for (const m of parens) {
    const inner = m[1];
    const tokens = inner.split(/[\/、,，\s×]+/);
    for (const t of tokens) {
      const trimmed = t.trim();
      if (!/^[A-Z]{2,5}$/.test(trimmed)) continue;
      if (TICKER_NOISE.has(trimmed)) continue;
      if (primary === null) primary = trimmed;
      found.add(trimmed);
    }
  }

  // 3) Inline tickers anywhere in heading (e.g., "WH/HLT × ChatGPT/Claude")
  for (const m of heading.matchAll(TICKER_RE)) {
    const t = m[1];
    if (t.length < 2) continue; // single letter is too noisy
    if (TICKER_NOISE.has(t)) continue;
    if (primary === null) primary = t;
    found.add(t);
  }

  return { primary, all: Array.from(found).sort() };
}

function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      // strip emoji and most punctuation, keep CJK + alphanumerics
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .trim()
      .replace(/\s+/g, "-")
      .slice(0, 80) || "section"
  );
}

export function parseDigest(date: string, raw: string): Digest {
  const lines = raw.split(/\r?\n/);

  // Collect intro (everything before first ## heading)
  let i = 0;
  const intro: string[] = [];
  while (i < lines.length && !lines[i].startsWith("## ")) {
    intro.push(lines[i]);
    i++;
  }

  const sectors: Sector[] = [];
  let calendar: string | null = null;
  const seenIds = new Set<string>();

  while (i < lines.length) {
    const line = lines[i];
    if (!line.startsWith("## ")) {
      i++;
      continue;
    }
    const sectorTitle = line.slice(3).trim();

    // Capture the sector body up to (but not including) the next ## heading
    const bodyLines: string[] = [];
    i++;
    while (i < lines.length && !lines[i].startsWith("## ")) {
      bodyLines.push(lines[i]);
      i++;
    }
    const sectorBody = bodyLines.join("\n").trim();

    if (sectorTitle.includes(CALENDAR_HEADING_MARKER)) {
      // Calendar section: keep the whole body, including the heading line.
      calendar = `## ${sectorTitle}\n\n${sectorBody}`.trim();
      continue;
    }

    // Strip horizontal rules and split body by ### subsections
    const cleanBody = sectorBody
      .split(/\r?\n/)
      .filter((l) => l.trim() !== "---")
      .join("\n");

    const subs: Subsection[] = [];
    const parts = cleanBody.split(/^### /m);
    // parts[0] is text before the first ### (may be empty / orphan paragraphs)
    const orphan = parts[0]?.trim();
    if (orphan) {
      // Treat orphan paragraphs as a synthetic subsection with no ticker
      const id = uniqueSlug(`${sectorTitle}-overview`, seenIds);
      subs.push({
        id,
        heading: "",
        primaryTicker: null,
        allTickers: [],
        bodyMd: orphan,
      });
    }
    for (let p = 1; p < parts.length; p++) {
      const chunk = parts[p];
      const nlIdx = chunk.indexOf("\n");
      const heading = (nlIdx === -1 ? chunk : chunk.slice(0, nlIdx)).trim();
      const body = (nlIdx === -1 ? "" : chunk.slice(nlIdx + 1)).trim();
      const { primary, all } = extractTickers(heading);
      const id = uniqueSlug(`${sectorTitle}-${heading}`, seenIds);
      subs.push({
        id,
        heading,
        primaryTicker: primary,
        allTickers: all,
        bodyMd: body,
      });
    }

    sectors.push({ name: sectorTitle, subsections: subs });
  }

  // Re-order sectors to match SECTOR_ORDER; unknown sectors keep input order
  // appended at the end.
  const known: Sector[] = [];
  const unknown: Sector[] = [];
  for (const s of sectors) {
    if ((SECTOR_ORDER as readonly string[]).includes(s.name)) known.push(s);
    else unknown.push(s);
  }
  known.sort(
    (a, b) =>
      (SECTOR_ORDER as readonly string[]).indexOf(a.name) -
      (SECTOR_ORDER as readonly string[]).indexOf(b.name)
  );

  return {
    date,
    intro: intro.join("\n").trim(),
    sectors: [...known, ...unknown],
    calendar,
  };
}

function uniqueSlug(s: string, seen: Set<string>): string {
  const base = slugify(s);
  if (!seen.has(base)) {
    seen.add(base);
    return base;
  }
  let n = 2;
  while (seen.has(`${base}-${n}`)) n++;
  const out = `${base}-${n}`;
  seen.add(out);
  return out;
}

// Collect every ticker that appears anywhere in the digest, deduped + sorted.
export function allTickers(digest: Digest): string[] {
  const set = new Set<string>();
  for (const sec of digest.sectors) {
    for (const sub of sec.subsections) {
      for (const t of sub.allTickers) set.add(t);
    }
  }
  return Array.from(set).sort();
}
