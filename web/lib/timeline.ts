import { listDigests, loadDigest } from "./digests";
import {
  buildEntityIndex,
  getEntityFamily,
  getRootEntities,
  getChildrenOf,
  matchEntities,
  type EntityDef,
} from "./entities";
import type { Digest } from "./parser";

export type Mention = {
  date: string;             // YYYY-MM-DD
  sectorName: string;
  subsectionId: string;     // anchor target on /digest/[date]
  subsectionHeading: string;
  bulletText: string;       // bullet body without "- " prefix
  /** Which entity in the family this mention matched (for the badge). */
  matchedEntity: EntityDef;
  /** All family entities present in this bullet (for breakdown counting). */
  matchedFamilyIds: string[];
  /** Non-family co-occurring entities (for the related list). */
  coEntities: string[];
  /** Source attribution names extracted from this bullet (for source filter). */
  sources: string[];
  /** True if the subsection heading itself names a family member, i.e. the
   *  whole subsection is dedicated to this entity. False = bullet only mentions
   *  the entity inline (often a passing reference). */
  viaHeading: boolean;
};

export type EntityTimeline = {
  entity: EntityDef;
  family: EntityDef[];      // root + descendants used for this timeline
  memberBreakdown: Array<{ entity: EntityDef; count: number }>;
  mentions: Mention[];      // sorted newest first
  totalMentions: number;
  daysCount: number;
  /** Map date → mention count, for sparkline. Spans the full digest date range. */
  perDay: Map<string, number>;
  allDates: string[];       // every digest date observed (oldest → newest)
  related: Array<{ entity: EntityDef; count: number }>;
  /** Top sources mentioned in this entity's bullets (chip text → count). */
  topSources: Array<{ name: string; count: number }>;
};

// Extract bullets from a subsection's body. Continuation lines (indented or
// starting with "  -") are appended to the prior bullet. Blank lines flush.
export function extractBullets(bodyMd: string): string[] {
  const lines = bodyMd.split(/\r?\n/);
  const bullets: string[] = [];
  let current: string[] = [];
  const flush = () => {
    if (current.length) {
      bullets.push(current.join("\n").trim());
      current = [];
    }
  };
  for (const ln of lines) {
    if (/^- /.test(ln)) {
      flush();
      current = [ln.replace(/^- /, "")];
    } else if (current.length && /^\s+/.test(ln)) {
      current.push(ln);
    } else if (current.length && ln.trim() === "") {
      flush();
    }
  }
  flush();
  return bullets;
}

// Pull a "source name" out of an inline markdown link like "[TMTB Slack](url)"
// or out of a "*来源：JPM Tech Sketch*" italic. Returns the human-readable text.
export function extractSources(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(/\[([^\]]+)\]\(https?:[^)]+\)/g)) out.push(m[1].trim());
  for (const m of text.matchAll(/\*来源[：:]\s*([^*]+)\*/g)) {
    const cleaned = m[1].replace(/\([^)]*\)$/, "").trim(); // strip trailing "(MM/DD)"
    if (cleaned) out.push(cleaned);
  }
  return out;
}

// Scan one digest for any family member. De-duplicates per (subsection, bullet)
// so an Anthropic + Claude mention in the same bullet only counts once toward
// the family timeline; the matched entity is the most-specific (longest-alias)
// family member found.
// Pick the most specific family member found: prefer a child over the root.
function pickMatched(famHits: EntityDef[], rootId: string): EntityDef {
  const child = famHits.find((e) => e.parentId === rootId);
  return child ?? famHits[0];
}

function mentionsForFamily(
  digest: Digest,
  family: EntityDef[],
  allEntities: EntityDef[]
): Mention[] {
  const familyIdx = buildEntityIndex(family);
  const allIdx = buildEntityIndex(allEntities);
  const familyIds = new Set(family.map((e) => e.id));
  const rootId = family[0].id;
  const out: Mention[] = [];

  for (const sec of digest.sectors) {
    for (const sub of sec.subsections) {
      // If the subsection heading mentions a family member, promote every
      // bullet inside as a family mention even when the bullet text doesn't
      // re-state the entity. Heading-only mentions (no bullet body) are
      // dropped — they carry no content beyond the section breadcrumb.
      const headFamHits = sub.heading ? matchEntities(sub.heading, familyIdx) : [];
      const headPromotes = headFamHits.length > 0;

      // If the heading itself names a *specific child* (e.g. "OpenAI (GPT-5.5
       // 发布与战略方向)"), the subsection's topic is that child even when a
      // bullet only references a sibling inline ("...低于 GPT-5.4"). Prefer
      // the heading's specific child over bullet hits in that case.
      const headHasChild = headFamHits.some((e) => e.parentId === rootId);

      const bullets = extractBullets(sub.bodyMd);
      for (const b of bullets) {
        const bulletFamHits = matchEntities(b, familyIdx);
        const matched = headHasChild
          ? pickMatched(headFamHits, rootId)
          : bulletFamHits.length > 0
            ? pickMatched(bulletFamHits, rootId)
            : headPromotes
              ? pickMatched(headFamHits, rootId)
              : null;
        if (!matched) continue;

        // Union of heading + bullet family hits, deduped by id (heading first
        // so its order wins on ties). Drives the family breakdown counter.
        const seen = new Set<string>();
        const familyHits: EntityDef[] = [];
        for (const e of [...headFamHits, ...bulletFamHits]) {
          if (!seen.has(e.id)) {
            seen.add(e.id);
            familyHits.push(e);
          }
        }
        const all = matchEntities(b, allIdx);
        out.push({
          date: digest.date,
          sectorName: sec.name,
          subsectionId: sub.id,
          subsectionHeading: sub.heading,
          bulletText: b,
          matchedEntity: matched,
          matchedFamilyIds: familyHits.map((x) => x.id),
          coEntities: all.map((x) => x.id).filter((id) => !familyIds.has(id)),
          sources: extractSources(b),
          viaHeading: headPromotes,
        });
      }
    }
  }
  return out;
}



/** Build the timeline for one root entity, including all child entities. */
export async function loadEntityTimeline(
  entityId: string
): Promise<EntityTimeline | null> {
  const family = getEntityFamily(entityId);
  if (family.length === 0) return null;
  const root = family[0];

  const allEntities = getRootEntities().flatMap((r) => getEntityFamily(r.id));

  const summaries = await listDigests();
  const allDates = summaries.map((s) => s.date).slice().reverse(); // oldest→newest

  const allMentions: Mention[] = [];
  for (const s of summaries) {
    const d = await loadDigest(s.date);
    if (!d) continue;
    allMentions.push(...mentionsForFamily(d, family, allEntities));
  }

  allMentions.sort((a, b) => b.date.localeCompare(a.date));

  const perDay = new Map<string, number>();
  for (const m of allMentions) perDay.set(m.date, (perDay.get(m.date) || 0) + 1);

  // Related = entities outside this family that co-occur in mention bullets.
  const coCount = new Map<string, number>();
  for (const m of allMentions) {
    for (const oid of m.coEntities) coCount.set(oid, (coCount.get(oid) || 0) + 1);
  }
  const related = Array.from(coCount.entries())
    .map(([oid, n]) => ({ entity: allEntities.find((e) => e.id === oid)!, count: n }))
    .filter((r) => !!r.entity)
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

  // Per-family-member breakdown counts ALL family hits per bullet, not just
  // the most-specific match. So a bullet mentioning "Anthropic ... Opus" gives
  // +1 to both. Sum may exceed total mentions; that's intentional — it tells
  // you the share of mindshare each member has.
  const memberCount = new Map<string, number>();
  for (const m of allMentions) {
    for (const fid of m.matchedFamilyIds) {
      memberCount.set(fid, (memberCount.get(fid) || 0) + 1);
    }
  }
  const memberBreakdown = family
    .map((e) => ({ entity: e, count: memberCount.get(e.id) || 0 }))
    .filter((b) => b.count > 0)
    .sort((a, b) => b.count - a.count);

  // Top sources, aggregated from per-mention extraction.
  const sourceCount = new Map<string, number>();
  for (const m of allMentions) {
    for (const s of m.sources) sourceCount.set(s, (sourceCount.get(s) || 0) + 1);
  }
  const topSources = Array.from(sourceCount.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([name, count]) => ({ name, count }));

  return {
    entity: root,
    family,
    memberBreakdown,
    mentions: allMentions,
    totalMentions: allMentions.length,
    daysCount: new Set(allMentions.map((m) => m.date)).size,
    perDay,
    allDates,
    related,
    topSources,
  };
}

export function listAvailableEntities(): EntityDef[] {
  return getRootEntities();
}
