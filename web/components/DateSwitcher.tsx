"use client";

import { useEffect, useRef, useState } from "react";
import { Menu } from "@base-ui/react/menu";
import { useRouter } from "next/navigation";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  current: string; // YYYY-MM-DD
  dates: string[]; // sorted desc, newest first
};

export default function DateSwitcher({ current, dates }: Props) {
  const router = useRouter();
  const idx = dates.indexOf(current);
  // dates is desc, so older = idx + 1, newer = idx - 1
  const older = idx >= 0 && idx < dates.length - 1 ? dates[idx + 1] : null;
  const newer = idx > 0 ? dates[idx - 1] : null;

  const [open, setOpen] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  // When the menu opens, center the current date in the scrollable popup so
  // the user lands oriented around "today" rather than at some arbitrary
  // offset chosen by the focus engine.
  useEffect(() => {
    if (!open) return;
    const raf = requestAnimationFrame(() => {
      const popup = popupRef.current;
      if (!popup) return;
      const active = popup.querySelector<HTMLElement>('[data-current="true"]');
      if (active) active.scrollIntoView({ block: "center" });
      else popup.scrollTop = 0;
    });
    return () => cancelAnimationFrame(raf);
  }, [open]);

  function go(date: string) {
    router.push(`/digest/${date}`);
  }

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => older && go(older)}
        disabled={!older}
        title={older ? `上一份：${older}` : "已是最早"}
        aria-label="上一份"
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>

      <Menu.Root open={open} onOpenChange={setOpen}>
        <Menu.Trigger
          className={cn(
            "group flex items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-sm font-medium",
            "text-primary transition-colors hover:bg-muted",
            "data-[popup-open]:bg-muted"
          )}
        >
          {current}
          <ChevronDown className="h-3.5 w-3.5 opacity-60 transition-transform group-data-[popup-open]:rotate-180" />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner
            sideOffset={6}
            align="center"
            collisionPadding={12}
            className="z-[60]"
          >
            <Menu.Popup
              ref={popupRef}
              className={cn(
                "z-[60] w-40 overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-lg",
                "max-h-[min(20rem,var(--available-height,20rem))]",
                "outline-none",
                "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0",
                "transition-opacity duration-150"
              )}
            >
              {dates.map((d) => {
                const active = d === current;
                return (
                  <Menu.Item
                    key={d}
                    onClick={() => go(d)}
                    data-current={active ? "true" : undefined}
                    className={cn(
                      "flex cursor-pointer items-center justify-between rounded px-2 py-1 font-mono text-[13px] outline-none",
                      "data-[highlighted]:bg-muted",
                      active
                        ? "font-medium text-primary"
                        : "text-foreground"
                    )}
                  >
                    <span>{d}</span>
                    {active && (
                      <span
                        aria-hidden
                        className="h-1.5 w-1.5 rounded-full bg-primary"
                      />
                    )}
                  </Menu.Item>
                );
              })}
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>

      <button
        type="button"
        onClick={() => newer && go(newer)}
        disabled={!newer}
        title={newer ? `下一份：${newer}` : "已是最新"}
        aria-label="下一份"
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
