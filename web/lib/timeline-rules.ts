/**
 * Rules controlling which mentions count as "primary" (shown by default) vs
 * "secondary" (folded behind a disclosure) on the entity timeline page.
 *
 * Edit this file when a new source/sector becomes important enough to surface
 * by default. All matches are case-insensitive substring matches.
 */

export type TimelineRules = {
  /** Sectors whose mentions are always primary, regardless of subsection. */
  primarySectors: string[];
  /** Source-chip names that promote a bullet to primary even if it sits in
   *  a non-primary sector (e.g. a TMTB pickup of a The Information scoop in
   *  the Macro sector still belongs in the Anthropic timeline by default). */
  primarySources: string[];
  /** Keep the original behaviour: any mention whose subsection heading
   *  directly names a family member is primary (e.g. `### Anthropic`). */
  promoteHeadingMatch: boolean;
};

export const TIMELINE_RULES: TimelineRules = {
  primarySectors: ["AI 模型与平台"],
  primarySources: ["The Information"],
  promoteHeadingMatch: true,
};

/** Case-insensitive substring match against a list. */
function ciIncludes(haystacks: string[], needle: string): boolean {
  const n = needle.toLowerCase();
  return haystacks.some((h) => h.toLowerCase().includes(n));
}

export function isPrimaryMention(
  m: { sectorName: string; sources: string[]; viaHeading: boolean },
  rules: TimelineRules = TIMELINE_RULES
): boolean {
  if (rules.primarySectors.includes(m.sectorName)) return true;
  if (rules.promoteHeadingMatch && m.viaHeading) return true;
  for (const src of m.sources) {
    if (ciIncludes(rules.primarySources, src)) return true;
  }
  return false;
}
