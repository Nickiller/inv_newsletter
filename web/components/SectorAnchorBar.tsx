"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Item = { name: string; anchorId: string; count: number };

type Props = {
  items: Item[]; // sectors that are currently visible (post-filter)
};

export default function SectorAnchorBar({ items }: Props) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const barRef = useRef<HTMLDivElement>(null);

  // Scroll-spy: pick the topmost sector heading near the top of the viewport.
  useEffect(() => {
    if (items.length === 0) return;
    const ids = items.map((i) => i.anchorId);

    const observer = new IntersectionObserver(
      () => {
        // Re-evaluate from scratch on any change: find the section whose top
        // is closest to (but past) the sticky-header offset.
        const offset = 130; // header (~56) + bar (~48) + breathing room
        let best: { id: string; dist: number } | null = null;
        for (const id of ids) {
          const el = document.getElementById(id);
          if (!el) continue;
          const top = el.getBoundingClientRect().top;
          // Sections that have already scrolled past the offset
          if (top - offset > 0) continue;
          const dist = Math.abs(top - offset);
          if (best === null || dist < best.dist) best = { id, dist };
        }
        // Fallback: nothing past offset → highlight the first upcoming one
        if (!best) {
          for (const id of ids) {
            const el = document.getElementById(id);
            if (!el) continue;
            const top = el.getBoundingClientRect().top;
            if (best === null || top < (best as unknown as { dist: number }).dist) {
              best = { id, dist: top };
            }
          }
        }
        setActiveId(best?.id ?? ids[0]);
      },
      { rootMargin: "0px", threshold: [0, 0.1, 0.5, 1] }
    );

    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    // Trigger once on mount in case sections are already in view
    requestAnimationFrame(() => {
      const ev = new Event("scroll");
      window.dispatchEvent(ev);
    });

    const onScroll = () => {
      const offset = 130;
      let best: { id: string; dist: number } | null = null;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (!el) continue;
        const top = el.getBoundingClientRect().top;
        if (top - offset > 0) continue;
        const dist = Math.abs(top - offset);
        if (best === null || dist < best.dist) best = { id, dist };
      }
      if (!best) {
        for (const id of ids) {
          const el = document.getElementById(id);
          if (!el) continue;
          const top = el.getBoundingClientRect().top;
          if (best === null || top < best.dist) best = { id, dist: top };
        }
      }
      setActiveId(best?.id ?? ids[0]);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
    };
  }, [items]);

  // Auto-scroll the active chip into view inside the horizontal bar
  useEffect(() => {
    if (!activeId || !barRef.current) return;
    const chip = barRef.current.querySelector<HTMLAnchorElement>(
      `[data-anchor="${activeId}"]`
    );
    if (chip) {
      chip.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
  }, [activeId]);

  function jump(e: React.MouseEvent<HTMLAnchorElement>, anchorId: string) {
    e.preventDefault();
    const el = document.getElementById(anchorId);
    if (!el) return;
    const offset = 110; // header + bar height
    const top =
      el.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top, behavior: "smooth" });
    history.replaceState(null, "", `#${anchorId}`);
  }

  if (items.length === 0) return null;

  return (
    <div
      ref={barRef}
      className="sticky top-12 z-10 -mx-8 mb-4 overflow-x-auto border-b border-border/70 bg-background/85 px-8 py-2.5 backdrop-blur-md"
    >
      <nav className="flex gap-2 whitespace-nowrap">
        {items.map((it) => {
          const active = it.anchorId === activeId;
          return (
            <a
              key={it.anchorId}
              href={`#${it.anchorId}`}
              data-anchor={it.anchorId}
              onClick={(e) => jump(e, it.anchorId)}
              className={cn(
                buttonVariants({ variant: active ? "default" : "outline", size: "sm" }),
                "group rounded-full no-underline! decoration-transparent!",
                active &&
                  "border-primary bg-primary text-primary-foreground! shadow-sm shadow-primary/30 hover:bg-primary/90"
              )}
            >
              <span className="tracking-tight">{it.name}</span>
              <Badge
                variant={active ? "secondary" : "secondary"}
                className={cn(
                  "h-[18px] min-w-[18px] px-1.5 text-[11px] tabular-nums",
                  active && "bg-primary-foreground/25 text-primary-foreground!"
                )}
              >
                {it.count}
              </Badge>
            </a>
          );
        })}
      </nav>
    </div>
  );
}
