/**
 * Entity dictionary for cross-digest timeline tracking.
 *
 * Tickers are sourced dynamically from the digests via parser.ts. Other
 * entities (companies, models, people) are curated here. Keep aliases
 * exact-case — investment-newsletter content uses canonical capitalisation
 * ("Anthropic", "OpenAI"), so case-sensitive matching is fine and avoids
 * false positives like "ms" inside other words.
 */

export type EntityType = "company" | "model" | "person" | "ticker";

export type EntityDef = {
  id: string;
  name: string;
  type: EntityType;
  aliases: string[];
  /** Parent company id. A timeline for the parent rolls up all descendants. */
  parentId?: string;
};

// Hierarchical: company-level entities aggregate mentions of their products,
// models, and key people. Visiting /entity/anthropic surfaces hits for Claude,
// Opus, etc., each tagged with which alias matched.
const CURATED: EntityDef[] = [
  // Anthropic + family
  { id: "anthropic",   name: "Anthropic",    type: "company", aliases: ["Anthropic"] },
  { id: "claude",      name: "Claude",       type: "model",   aliases: ["Claude"],       parentId: "anthropic" },
  { id: "claude-code", name: "Claude Code",  type: "model",   aliases: ["Claude Code"],  parentId: "anthropic" },
  { id: "opus",        name: "Opus",         type: "model",   aliases: ["Opus"],         parentId: "anthropic" },
  { id: "sonnet",      name: "Sonnet",       type: "model",   aliases: ["Sonnet"],       parentId: "anthropic" },

  // OpenAI + family
  { id: "openai",     name: "OpenAI",   type: "company", aliases: ["OpenAI"] },
  { id: "chatgpt",    name: "ChatGPT",  type: "model",   aliases: ["ChatGPT"],   parentId: "openai" },
  { id: "gpt-55",     name: "GPT-5.5",  type: "model",   aliases: ["GPT-5.5"],   parentId: "openai" },
  { id: "codex",      name: "Codex",    type: "model",   aliases: ["Codex"],     parentId: "openai" },
  { id: "sam-altman", name: "Sam Altman", type: "person", aliases: ["Sam Altman"], parentId: "openai" },
];

/** All entities whose timeline aggregates children — i.e. companies. Used
 * to render the top-level "实体时间线" entry on the home page. */
export function getRootEntities(): EntityDef[] {
  return CURATED.filter((e) => !e.parentId);
}

/** Direct children of `parentId`. */
export function getChildrenOf(parentId: string): EntityDef[] {
  return CURATED.filter((e) => e.parentId === parentId);
}

/** Self + all descendants — used to scan mentions for an aggregating entity. */
export function getEntityFamily(id: string): EntityDef[] {
  const root = CURATED.find((e) => e.id === id);
  if (!root) return [];
  return [root, ...getChildrenOf(id)];
}

/** Every curated entity (every level of the hierarchy). */
export function getAllCurated(): EntityDef[] {
  return CURATED;
}

/** Build ticker entities from a flat list of ticker symbols (already filtered). */
export function getTickerEntities(tickers: string[]): EntityDef[] {
  return tickers.map((t) => ({
    id: t.toLowerCase(),
    name: t,
    type: "ticker" as const,
    aliases: [t],
  }));
}

/** Curated + tickers, de-duped (curated wins on collisions). */
export function getAllEntities(tickers: string[]): EntityDef[] {
  const map = new Map<string, EntityDef>();
  for (const e of CURATED) map.set(e.id, e);
  for (const e of getTickerEntities(tickers)) {
    if (!map.has(e.id)) map.set(e.id, e);
  }
  return Array.from(map.values());
}

export type EntityIndex = {
  pattern: RegExp;
  byAlias: Map<string, EntityDef>;
};

const escRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const ASCII_RE = /^[A-Za-z0-9.\-+\s]+$/;

/** Build a single combined regex matching every alias.
 *  ASCII aliases get word boundaries; CJK aliases are matched literally. */
export function buildEntityIndex(entities: EntityDef[]): EntityIndex {
  const aliases: Array<{ alias: string; entity: EntityDef }> = [];
  for (const e of entities) for (const a of e.aliases) aliases.push({ alias: a, entity: e });
  // Longest first so multi-word aliases win
  aliases.sort((a, b) => b.alias.length - a.alias.length);

  const parts = aliases.map(({ alias }) =>
    ASCII_RE.test(alias) ? `\\b${escRe(alias)}\\b` : escRe(alias)
  );
  const byAlias = new Map<string, EntityDef>();
  for (const a of aliases) byAlias.set(a.alias, a.entity);
  return { pattern: new RegExp(parts.join("|"), "g"), byAlias };
}

/** Returns unique entities found in `text` (preserves first-match order). */
export function matchEntities(text: string, idx: EntityIndex): EntityDef[] {
  const seen = new Set<string>();
  const out: EntityDef[] = [];
  for (const m of text.matchAll(idx.pattern)) {
    const e = idx.byAlias.get(m[0]);
    if (e && !seen.has(e.id)) {
      seen.add(e.id);
      out.push(e);
    }
  }
  return out;
}
