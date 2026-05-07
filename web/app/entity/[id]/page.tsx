import Link from "next/link";
import { notFound } from "next/navigation";
import { loadEntityTimeline, listAvailableEntities } from "@/lib/timeline";
import MarkdownSection from "@/components/MarkdownSection";
import { Sparkline } from "@/components/Sparkline";
import { ThemeToggle } from "@/components/ThemeToggle";
import type { Mention } from "@/lib/timeline";
import { isPrimaryMention } from "@/lib/timeline-rules";

export const dynamic = "force-dynamic";

function fmtDateZh(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${parseInt(m, 10)}月${parseInt(d, 10)}日`;
}

function isPrimary(m: Mention): boolean {
  return isPrimaryMention(m);
}

function groupByDate(
  mentions: Mention[]
): Array<{ date: string; primary: Mention[]; secondary: Mention[] }> {
  const map = new Map<string, { primary: Mention[]; secondary: Mention[] }>();
  for (const m of mentions) {
    const slot = map.get(m.date) || { primary: [], secondary: [] };
    if (isPrimary(m)) slot.primary.push(m);
    else slot.secondary.push(m);
    map.set(m.date, slot);
  }
  return Array.from(map.entries()).map(([date, v]) => ({ date, ...v }));
}

// Build a URL on the same page that toggles the given filter on/off,
// preserving any other active filter.
function toggleFilter(
  basePath: string,
  current: { member: string | null; source: string | null },
  key: "member" | "source",
  value: string
): string {
  const next = { ...current };
  next[key] = current[key] === value ? null : value;
  const qs = new URLSearchParams();
  if (next.member) qs.set("member", next.member);
  if (next.source) qs.set("source", next.source);
  const s = qs.toString();
  return s ? `${basePath}?${s}` : basePath;
}

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function EntityPage(
  props: PageProps<"/entity/[id]"> & { searchParams: SearchParams }
) {
  const [{ id }, params] = await Promise.all([props.params, props.searchParams]);
  const timeline = await loadEntityTimeline(id);
  if (!timeline) notFound();

  const memberFilter = typeof params.member === "string" ? params.member : null;
  const sourceFilter = typeof params.source === "string" ? params.source : null;

  const {
    entity,
    family,
    memberBreakdown,
    mentions: allMentions,
    daysCount,
    perDay,
    allDates,
    related,
    topSources,
  } = timeline;

  const mentions = allMentions.filter((m) => {
    if (memberFilter && !m.matchedFamilyIds.includes(memberFilter)) return false;
    if (sourceFilter && !m.sources.includes(sourceFilter)) return false;
    return true;
  });

  const sparkValues = allDates.map((d) => perDay.get(d) || 0);
  const others = listAvailableEntities().filter((e) => e.id !== entity.id);
  const days = groupByDate(mentions);
  const primaryCount = mentions.filter(isPrimary).length;
  const secondaryCount = mentions.length - primaryCount;
  const basePath = `/entity/${entity.id}`;
  const filterState = { member: memberFilter, source: sourceFilter };
  const isFiltering = memberFilter !== null || sourceFilter !== null;

  return (
    <main className="reader-shell min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3.5">
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
            ← 全部日期
          </Link>
          <h1 className="reader-title text-[17px] text-foreground">实体时间线</h1>
          <div className="flex items-center gap-3">
            {others.map((o) => (
              <Link
                key={o.id}
                href={`/entity/${o.id}`}
                className="text-xs text-muted-foreground hover:text-primary"
              >
                {o.name}
              </Link>
            ))}
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-3xl px-6 pb-16 pt-8">
        <section className="mb-8 grid grid-cols-[1fr_auto] items-end gap-6 border-b border-border pb-6">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {entity.type}
              {family.length > 1 ? ` · ${family.length - 1} 个相关产品/人` : ""}
            </div>
            <h2 className="reader-title mb-3 text-[40px] leading-tight text-foreground">
              {entity.name}
            </h2>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm text-muted-foreground">
              <span>
                <span className="reader-title mr-1.5 text-[22px] text-foreground">
                  {allMentions.length}
                </span>
                次提及
              </span>
              <span>
                <span className="reader-title mr-1.5 text-[22px] text-foreground">
                  {daysCount}
                </span>
                天
              </span>
              <span>
                跨度{" "}
                <span className="text-foreground">
                  {allDates[0] || "—"} → {allDates[allDates.length - 1] || "—"}
                </span>
              </span>
            </div>
          </div>
          <Sparkline
            values={sparkValues}
            ariaLabel={`${entity.name} 提及频次按日`}
            className="text-primary"
          />
        </section>

        {(() => {
          const people = memberBreakdown.filter((m) => m.entity.type === "person");
          const nonPeople = memberBreakdown.filter((m) => m.entity.type !== "person");
          const renderChip = (m: (typeof memberBreakdown)[number]) => {
            const active = memberFilter === m.entity.id;
            return (
              <Link
                key={m.entity.id}
                href={toggleFilter(basePath, filterState, "member", m.entity.id)}
                className={
                  "inline-flex items-baseline gap-1.5 rounded-full px-2.5 py-0.5 text-xs transition " +
                  (active
                    ? "bg-primary text-primary-foreground"
                    : "bg-card text-foreground hover:bg-accent hover:text-accent-foreground")
                }
                scroll={false}
              >
                <span>{m.entity.name}</span>
                <span
                  className={
                    "font-mono text-[10px] " +
                    (active ? "opacity-80" : "text-muted-foreground")
                  }
                >
                  {m.count}
                </span>
              </Link>
            );
          };
          return (
            <>
              {nonPeople.length > 1 && (
                <section className="mb-6">
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    家族构成 · 点击筛选
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {nonPeople.map(renderChip)}
                  </div>
                </section>
              )}
              {people.length > 0 && (
                <section className="mb-8">
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    人物 · 点击筛选
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {people.map(renderChip)}
                  </div>
                </section>
              )}
            </>
          );
        })()}

        {topSources.length > 0 && (
          <section className="mb-10">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              主要来源 · 点击筛选
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {topSources.map((s) => {
                const active = sourceFilter === s.name;
                return (
                  <Link
                    key={s.name}
                    href={toggleFilter(basePath, filterState, "source", s.name)}
                    className={
                      "inline-flex items-baseline gap-1 rounded-full px-2.5 py-0.5 text-xs transition " +
                      (active
                        ? "bg-primary text-primary-foreground"
                        : "border border-border bg-card text-muted-foreground hover:border-primary hover:text-primary")
                    }
                    scroll={false}
                  >
                    {s.name}
                    <span
                      className={
                        "font-mono text-[10px] " +
                        (active ? "opacity-80" : "text-muted-foreground/70")
                      }
                    >
                      {s.count}
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        <section>
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              时间线 · {primaryCount} 条主条目 / {days.length} 天
              {secondaryCount > 0 && (
                <span className="ml-1.5 normal-case tracking-normal text-muted-foreground">
                  + {secondaryCount} 条附带提及
                </span>
              )}
              {isFiltering && (
                <span className="ml-2 normal-case tracking-normal text-muted-foreground">
                  · 已筛选
                </span>
              )}
            </h3>
            {isFiltering && (
              <Link
                href={basePath}
                className="text-xs text-muted-foreground hover:text-primary"
                scroll={false}
              >
                清除筛选
              </Link>
            )}
          </div>

          {days.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-card px-4 py-6 text-sm text-muted-foreground">
              当前筛选下没有内容。
            </p>
          ) : (
            <ol className="relative space-y-6 border-l border-border pl-6">
              {days.map(({ date, primary, secondary }) => {
                const dayHasPrimary = primary.length > 0;
                const renderItem = (m: Mention, i: number) => (
                  <article
                    key={`${m.subsectionId}-${i}`}
                    className={i > 0 ? "border-t border-border/60 pt-3" : ""}
                  >
                    <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                      <span className="font-medium">
                        {m.sectorName}
                        {m.subsectionHeading ? ` · ${m.subsectionHeading}` : ""}
                      </span>
                      {m.matchedEntity.id !== entity.id && (
                        <span
                          className="rounded-full bg-accent px-1.5 py-px text-[10px] text-accent-foreground"
                          title="该条命中的家族成员"
                        >
                          {m.matchedEntity.name}
                        </span>
                      )}
                    </div>
                    <div className="prose-digest mention-card -mx-1 px-1">
                      <MarkdownSection date={m.date} markdown={m.bulletText} />
                    </div>
                  </article>
                );

                return (
                  <li key={date} className="relative">
                    <span
                      aria-hidden
                      className={
                        "absolute -left-[31px] top-2 h-3 w-3 rounded-full border-2 bg-background " +
                        (dayHasPrimary ? "border-primary" : "border-muted-foreground/40")
                      }
                    />
                    <div className="mb-2 flex items-baseline justify-between gap-3">
                      <div className="flex items-baseline gap-3">
                        <span
                          className={
                            "reader-title text-[20px] font-semibold " +
                            (dayHasPrimary ? "text-foreground" : "text-muted-foreground")
                          }
                        >
                          {fmtDateZh(date)}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">{date}</span>
                        <span className="text-xs text-muted-foreground">
                          {dayHasPrimary
                            ? `· ${primary.length} 条主条目`
                            : `· ${secondary.length} 条附带提及`}
                        </span>
                      </div>
                      <Link
                        href={`/digest/${date}`}
                        className="text-xs text-muted-foreground hover:text-primary"
                      >
                        在日报中查看 →
                      </Link>
                    </div>

                    {dayHasPrimary ? (
                      <>
                        <div className="space-y-2.5 rounded-lg border border-border bg-card px-4 py-3">
                          {primary.map((m, i) => renderItem(m, i))}
                        </div>
                        {secondary.length > 0 && (
                          <details className="mt-2 group">
                            <summary className="cursor-pointer list-none text-xs text-muted-foreground hover:text-primary">
                              <span className="inline-block transition group-open:rotate-90">›</span>{" "}
                              展开 {secondary.length} 条其他板块的附带提及
                            </summary>
                            <div className="mt-2 space-y-2.5 rounded-lg border border-dashed border-border/70 bg-card/60 px-4 py-3">
                              {secondary.map((m, i) => renderItem(m, i))}
                            </div>
                          </details>
                        )}
                      </>
                    ) : (
                      <details className="group">
                        <summary className="cursor-pointer list-none text-xs text-muted-foreground hover:text-primary">
                          <span className="inline-block transition group-open:rotate-90">›</span>{" "}
                          展开附带提及
                        </summary>
                        <div className="mt-2 space-y-2.5 rounded-lg border border-dashed border-border/70 bg-card/60 px-4 py-3">
                          {secondary.map((m, i) => renderItem(m, i))}
                        </div>
                      </details>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </section>

        {related.length > 0 && (
          <section className="mt-12 border-t border-border pt-6">
            <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              共现实体
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {related.map((r) => (
                <Link
                  key={r.entity.id}
                  href={`/entity/${r.entity.id}`}
                  className="inline-flex items-baseline gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                >
                  {r.entity.name}
                  <span className="font-mono text-[10px] opacity-70">{r.count}</span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
