"use client";

import { useMemo, useState } from "react";

type Props = {
  tickers: string[]; // all tickers available
  selectedTickers: Set<string>;
  onToggleTicker: (t: string) => void;
  onClearTickers: () => void;

  onClearAll: () => void;
};

export default function FilterSidebar({
  tickers,
  selectedTickers,
  onToggleTicker,
  onClearTickers,
  onClearAll,
}: Props) {
  const [search, setSearch] = useState("");

  const filteredTickers = useMemo(() => {
    if (!search.trim()) return tickers;
    const q = search.trim().toUpperCase();
    return tickers.filter((t) => t.includes(q));
  }, [tickers, search]);

  return (
    <aside className="sticky top-14 max-h-[calc(100vh-3.5rem)] overflow-y-auto border-l border-border bg-background p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          过滤
        </h2>
        <button
          type="button"
          onClick={onClearAll}
          className="text-xs text-primary hover:underline"
        >
          重置全部
        </button>
      </div>

      <section className="mt-5">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-foreground">
            Ticker（{selectedTickers.size}/{tickers.length}）
          </h3>
          {selectedTickers.size > 0 && (
            <button
              type="button"
              onClick={onClearTickers}
              className="text-xs text-muted-foreground hover:text-primary"
            >
              清空
            </button>
          )}
        </div>
        <input
          type="text"
          placeholder="搜索 (如 AAPL)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mt-2 w-full rounded border border-border bg-background px-2 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {filteredTickers.length === 0 ? (
            <span className="text-xs text-muted-foreground">无匹配</span>
          ) : (
            filteredTickers.map((t) => {
              const active = selectedTickers.has(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => onToggleTicker(t)}
                  className={
                    "rounded-full px-2.5 py-0.5 text-xs font-mono transition " +
                    (active
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-foreground hover:bg-muted/70")
                  }
                >
                  {t}
                </button>
              );
            })
          )}
        </div>
        {selectedTickers.size > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            提示：选中 ticker 时，无 ticker 关联的子节会被隐藏。
          </p>
        )}
      </section>
    </aside>
  );
}
