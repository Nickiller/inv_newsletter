"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Digest, Subsection } from "@/lib/parser";
import FilterSidebar from "./FilterSidebar";
import MarkdownSection from "./MarkdownSection";
import SectorAnchorBar from "./SectorAnchorBar";
import TickerOutlineRail from "./TickerOutlineRail";

type Props = {
  digest: Digest;
  allTickers: string[];
};

function parseSetParam(v: string | null): Set<string> {
  if (!v) return new Set();
  return new Set(v.split(",").map((s) => s.trim()).filter(Boolean));
}

// Stable, URL-safe-ish anchor id derived from sector index.
function sectorAnchorId(idx: number): string {
  return `sector-${idx}`;
}

export default function DigestView({ digest, allTickers }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const sectorNames = useMemo(
    () => digest.sectors.map((s) => s.name),
    [digest]
  );

  const initialSectors = useMemo(() => {
    const fromUrl = parseSetParam(searchParams.get("sectors"));
    if (fromUrl.size === 0) return new Set<string>(sectorNames);
    return fromUrl;
  }, [searchParams, sectorNames]);

  const initialTickers = useMemo(
    () => parseSetParam(searchParams.get("tickers")),
    [searchParams]
  );

  const [selectedSectors, setSelectedSectors] =
    useState<Set<string>>(initialSectors);
  const [selectedTickers, setSelectedTickers] =
    useState<Set<string>>(initialTickers);

  useEffect(() => {
    const params = new URLSearchParams();
    const isAllSectors =
      selectedSectors.size === sectorNames.length &&
      sectorNames.every((s) => selectedSectors.has(s));
    if (!isAllSectors && selectedSectors.size > 0) {
      params.set("sectors", Array.from(selectedSectors).join(","));
    }
    if (selectedTickers.size > 0) {
      params.set("tickers", Array.from(selectedTickers).join(","));
    }
    const qs = params.toString();
    const next = qs ? `${pathname}?${qs}` : pathname;
    router.replace(next, { scroll: false });
  }, [selectedSectors, selectedTickers, sectorNames, pathname, router]);

  const toggleSector = useCallback((s: string) => {
    setSelectedSectors((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  }, []);

  const toggleTicker = useCallback((t: string) => {
    setSelectedTickers((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }, []);

  const clearTickers = useCallback(() => setSelectedTickers(new Set()), []);

  const clearAll = useCallback(() => {
    setSelectedSectors(new Set(sectorNames));
    setSelectedTickers(new Set());
  }, [sectorNames]);

  const subsectionVisible = useCallback(
    (sub: Subsection): boolean => {
      if (selectedTickers.size === 0) return true;
      return sub.allTickers.some((t) => selectedTickers.has(t));
    },
    [selectedTickers]
  );

  const visibleSectors = digest.sectors
    .map((s, idx) => ({ ...s, originalIdx: idx }))
    .filter((s) => selectedSectors.has(s.name))
    .map((s) => ({
      ...s,
      subsections: s.subsections.filter(subsectionVisible),
    }))
    .filter((s) => s.subsections.length > 0);

  const totalVisible = visibleSectors.reduce(
    (sum, s) => sum + s.subsections.length,
    0
  );

  const anchorItems = visibleSectors.map((s) => ({
    name: s.name,
    anchorId: sectorAnchorId(s.originalIdx),
    count: s.subsections.length,
  }));

  // Rail shows every sector in the digest (not just currently-visible ones)
  // so users can toggle visibility from the outline itself. Items are still
  // filtered by the active ticker filter to stay in sync with the main pane.
  const railGroups = digest.sectors.map((s, idx) => ({
    sectorName: s.name,
    sectorAnchorId: sectorAnchorId(idx),
    visible: selectedSectors.has(s.name),
    items: s.subsections
      .filter(subsectionVisible)
      .filter((sub) => sub.heading)
      .map((sub) => ({ id: sub.id, heading: sub.heading })),
  }));

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-[1fr_260px] gap-0 lg:grid-cols-[240px_minmax(0,1fr)_260px]">
      <TickerOutlineRail groups={railGroups} onToggleVisible={toggleSector} />

      <article className="prose-digest min-w-0 mx-auto w-full max-w-[760px] px-8 py-6">
        <SectorAnchorBar items={anchorItems} />

        {digest.intro && (
          <div className="mb-6 border-b border-border pb-4 pt-2">
            <MarkdownSection date={digest.date} markdown={digest.intro} />
          </div>
        )}

        {totalVisible === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-card px-6 py-10 text-center text-sm text-muted-foreground">
            当前过滤条件下没有内容。试试取消勾选 ticker 或 重置全部。
          </div>
        ) : (
          visibleSectors.map((sec) => (
            <section
              key={sec.name}
              id={sectorAnchorId(sec.originalIdx)}
              data-sector={sec.name}
              className="mb-2 scroll-mt-28"
            >
              <h2>{sec.name}</h2>
              {sec.subsections.map((sub) => (
                <section
                  key={sub.id}
                  data-subsection={sub.id}
                  data-tickers={sub.allTickers.join(",")}
                  id={sub.id}
                  className="scroll-mt-28"
                >
                  {sub.heading && (
                    <h3 className="sticky top-[96px] z-[5] -mx-8! mt-0! mb-2! border-b border-border/60 bg-background/85 px-8 py-2! backdrop-blur-md">
                      {sub.heading}
                    </h3>
                  )}
                  <MarkdownSection date={digest.date} markdown={sub.bodyMd} />
                </section>
              ))}
            </section>
          ))
        )}

        {digest.calendar && (
          <section className="mt-8 rounded-lg border border-border bg-card px-5 py-4">
            <MarkdownSection
              date={digest.date}
              markdown={digest.calendar}
            />
          </section>
        )}
      </article>

      <FilterSidebar
        tickers={allTickers}
        selectedTickers={selectedTickers}
        onToggleTicker={toggleTicker}
        onClearTickers={clearTickers}
        onClearAll={clearAll}
      />
    </div>
  );
}
