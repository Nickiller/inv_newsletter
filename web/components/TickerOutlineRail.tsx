"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type RailGroup = {
  sectorName: string;
  sectorAnchorId: string;
  visible: boolean;
  items: { id: string; heading: string }[];
};

type Props = {
  groups: RailGroup[];
  onToggleVisible: (sectorName: string) => void;
};

export default function TickerOutlineRail({ groups, onToggleVisible }: Props) {
  const [activeId, setActiveId] = useState<string | null>(null);
  // override[sectorAnchorId]: true = force collapsed, false = force expanded.
  // Absent = follow auto behavior (only the active sector is expanded).
  const [override, setOverride] = useState<Record<string, boolean>>({});
  const railRef = useRef<HTMLElement>(null);

  // Scroll-spy must consider every item in any visible sector, regardless of
  // whether the sector is currently collapsed in the rail UI — otherwise no
  // sector ever becomes active and nothing ever auto-expands.
  const spyIds = useMemo(
    () => groups.filter((g) => g.visible).flatMap((g) => g.items.map((i) => i.id)),
    [groups]
  );

  useEffect(() => {
    if (spyIds.length === 0) return;
    const offset = 160; // header (~48) + sector bar (~48) + sticky h3 (~48) + breathing room

    const recompute = () => {
      let best: { id: string; dist: number } | null = null;
      for (const id of spyIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        const top = el.getBoundingClientRect().top;
        if (top - offset > 0) continue;
        const dist = Math.abs(top - offset);
        if (best === null || dist < best.dist) best = { id, dist };
      }
      if (!best) {
        for (const id of spyIds) {
          const el = document.getElementById(id);
          if (!el) continue;
          const top = el.getBoundingClientRect().top;
          if (best === null || top < best.dist) best = { id, dist: top };
        }
      }
      setActiveId(best?.id ?? spyIds[0]);
    };

    recompute();
    window.addEventListener("scroll", recompute, { passive: true });
    window.addEventListener("resize", recompute);
    return () => {
      window.removeEventListener("scroll", recompute);
      window.removeEventListener("resize", recompute);
    };
  }, [spyIds]);

  // Which sector currently owns the active subsection.
  const activeSectorAnchorId = useMemo(() => {
    if (!activeId) return null;
    const g = groups.find((g) => g.items.some((i) => i.id === activeId));
    return g?.sectorAnchorId ?? null;
  }, [activeId, groups]);

  function isExpanded(g: RailGroup): boolean {
    if (!g.visible || g.items.length === 0) return false;
    if (g.sectorAnchorId in override) return !override[g.sectorAnchorId];
    return g.sectorAnchorId === activeSectorAnchorId;
  }

  // Keep active item in view inside the rail (only when it's actually rendered).
  useEffect(() => {
    if (!activeId || !railRef.current) return;
    const el = railRef.current.querySelector<HTMLAnchorElement>(
      `[data-rail-id="${activeId}"]`
    );
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeId, activeSectorAnchorId, override]);

  function jump(e: React.MouseEvent<HTMLAnchorElement>, id: string) {
    e.preventDefault();
    const el = document.getElementById(id);
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.scrollY - 140;
    window.scrollTo({ top, behavior: "smooth" });
    history.replaceState(null, "", `#${id}`);
  }

  function toggleCollapsed(g: RailGroup) {
    const currentlyExpanded = isExpanded(g);
    const auto = g.sectorAnchorId === activeSectorAnchorId; // auto-expanded?
    const nextExpanded = !currentlyExpanded;
    // If user's toggle matches auto behavior, drop the override so the sector
    // returns to following the active state.
    if (nextExpanded === auto) {
      setOverride((prev) => {
        const next = { ...prev };
        delete next[g.sectorAnchorId];
        return next;
      });
    } else {
      setOverride((prev) => ({ ...prev, [g.sectorAnchorId]: !nextExpanded }));
    }
  }

  if (groups.length === 0) return null;

  return (
    <aside
      ref={railRef}
      className="sticky top-14 hidden max-h-[calc(100vh-3.5rem)] overflow-y-auto border-r border-border/70 px-5 py-6 lg:block"
    >
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        On this page
      </h2>
      <nav className="space-y-3 text-[13px]">
        {groups.map((g) => {
          const expanded = isExpanded(g);
          return (
            <div key={g.sectorAnchorId}>
              <div
                className={
                  "group/sec flex items-center gap-1 rounded px-1 py-0.5 " +
                  (g.visible ? "" : "opacity-50")
                }
              >
                <button
                  type="button"
                  onClick={() => toggleCollapsed(g)}
                  disabled={!g.visible || g.items.length === 0}
                  aria-label={expanded ? "折叠" : "展开"}
                  className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
                >
                  <svg
                    className={
                      "h-2.5 w-2.5 transition-transform " +
                      (expanded ? "rotate-90" : "")
                    }
                    viewBox="0 0 12 12"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path
                      d="M4 2 L8 6 L4 10"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <span
                  className="flex-1 truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground/90"
                  title={g.sectorName}
                >
                  {g.sectorName}
                </span>
                <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/60">
                  {g.items.length}
                </span>
                <button
                  type="button"
                  onClick={() => onToggleVisible(g.sectorName)}
                  aria-label={`${g.visible ? "隐藏" : "显示"} ${g.sectorName}`}
                  title={g.visible ? "隐藏此板块" : "显示此板块"}
                  className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-muted-foreground/60 hover:bg-muted hover:text-foreground"
                >
                  {g.visible ? (
                    <svg
                      className="h-3 w-3"
                      viewBox="0 0 16 16"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z" />
                      <circle cx="8" cy="8" r="2" />
                    </svg>
                  ) : (
                    <svg
                      className="h-3 w-3"
                      viewBox="0 0 16 16"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M2.5 3.5l11 9" />
                      <path d="M6.5 4.2C7 4.07 7.5 4 8 4c4 0 6.5 4 6.5 4s-.7 1.1-2 2.3" />
                      <path d="M11.4 11.4C10.4 12.13 9.3 12.5 8 12.5c-4 0-6.5-4.5-6.5-4.5s1.1-1.9 3-3.2" />
                    </svg>
                  )}
                </button>
              </div>
              {expanded && (
                <ul className="mt-1 space-y-px">
                  {g.items.map((it) => {
                    const active = it.id === activeId;
                    return (
                      <li key={it.id} className="relative">
                        <span
                          aria-hidden
                          className={
                            "absolute left-0 top-1.5 h-[calc(100%-0.75rem)] w-px transition-colors " +
                            (active ? "bg-primary" : "bg-border")
                          }
                        />
                        <a
                          href={`#${it.id}`}
                          data-rail-id={it.id}
                          onClick={(e) => jump(e, it.id)}
                          className={
                            "block truncate rounded-r-md py-1 pl-3 pr-2 no-underline! transition-colors " +
                            (active
                              ? "font-medium text-primary!"
                              : "text-muted-foreground! hover:text-foreground!")
                          }
                          title={it.heading}
                        >
                          {it.heading}
                        </a>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
