import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  BookOpenText,
  CalendarDays,
  Gauge,
  Layers3,
  Tags,
} from "lucide-react";
import { SECTOR_ORDER } from "@/lib/constants";
import { listDigests, loadDigest } from "@/lib/digests";
import type { Digest } from "@/lib/parser";

export const dynamic = "force-dynamic";

type ArchiveDigest = {
  date: string;
  intro: string;
  sectorCount: number;
  tickerCount: number;
  topSector: string;
  topSectorCount: number;
  topTickers: string[];
  sectorNames: string[];
  imageCount: number;
};

const matrixColors = [
  "bg-teal-500",
  "bg-blue-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-emerald-500",
  "bg-violet-500",
  "bg-stone-500 dark:bg-zinc-400",
];

export default async function ArchiveConceptPage() {
  const summaries = await listDigests();
  const loaded = await Promise.all(
    summaries.map(async (summary) => ({
      summary,
      digest: await loadDigest(summary.date),
    }))
  );
  const items = loaded
    .filter((item): item is { summary: typeof summaries[number]; digest: Digest } =>
      Boolean(item.digest)
    )
    .map(({ summary, digest }) => toArchiveDigest(summary, digest));

  const latest = items[0];
  const oldest = items[items.length - 1];
  const averageTickers =
    items.length === 0
      ? 0
      : Math.round(
          items.reduce((sum, item) => sum + item.tickerCount, 0) / items.length
        );
  const globalTickers = buildGlobalTickers(
    loaded.flatMap((item) => (item.digest ? [item.digest] : []))
  );
  const maxTickerCount = Math.max(0, ...items.map((item) => item.tickerCount));

  return (
    <main className="min-h-screen bg-[#f6f7f2] text-stone-950 dark:bg-[#101312] dark:text-stone-100">
      <header className="sticky top-0 z-30 border-b border-stone-200 bg-[#f6f7f2]/92 backdrop-blur-md dark:border-zinc-800 dark:bg-[#101312]/92">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-medium text-stone-700 transition hover:border-stone-400 hover:text-stone-950 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-500 dark:hover:text-white"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="hidden sm:inline">当前列表</span>
          </Link>

          <div className="min-w-0 text-center">
            <div className="truncate text-sm font-semibold uppercase tracking-[0.16em] text-stone-500 dark:text-zinc-400">
              Research Archive
            </div>
            <h1 className="truncate text-base font-semibold text-stone-950 dark:text-white">
              日报列表概念
            </h1>
          </div>

          <Link
            href="/concept"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-stone-950 px-3 text-sm font-medium text-white transition hover:bg-stone-800 dark:bg-zinc-50 dark:text-zinc-950 dark:hover:bg-zinc-200"
          >
            <Gauge className="h-4 w-4" />
            <span className="hidden sm:inline">驾驶舱</span>
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:py-8">
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile
            icon={<CalendarDays className="h-4 w-4" />}
            label="日报"
            value={String(items.length)}
            detail={oldest && latest ? `${oldest.date} 至 ${latest.date}` : "暂无"}
          />
          <MetricTile
            icon={<Tags className="h-4 w-4" />}
            label="平均 Ticker"
            value={String(averageTickers)}
            detail={`${globalTickers.length} 个历史出现`}
          />
          <MetricTile
            icon={<Layers3 className="h-4 w-4" />}
            label="核心板块"
            value={latest?.topSector ?? "-"}
            detail={latest ? `最新 ${latest.topSectorCount} 条` : "暂无"}
          />
          <MetricTile
            icon={<Activity className="h-4 w-4" />}
            label="最新日报"
            value={latest?.date ?? "-"}
            detail={latest ? `${latest.sectorCount} 板块 / ${latest.tickerCount} tickers` : "暂无"}
          />
        </section>

        {latest && (
          <section className="mt-6 rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="grid gap-px bg-stone-200 dark:bg-zinc-800 lg:grid-cols-[340px_minmax(0,1fr)_260px]">
              <div className="bg-white p-5 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                  Latest Brief
                </p>
                <h2 className="mt-3 text-4xl font-semibold tracking-tight text-stone-950 dark:text-white">
                  {latest.date}
                </h2>
                <p className="mt-1 text-sm text-stone-500 dark:text-zinc-400">
                  {weekday(latest.date)}
                </p>
              </div>
              <div className="bg-white p-5 dark:bg-zinc-950">
                <p className="line-clamp-3 text-sm leading-6 text-stone-700 dark:text-zinc-200">
                  {latest.intro || "暂无摘要预览。"}
                </p>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {latest.topTickers.slice(0, 9).map((ticker) => (
                    <span
                      key={ticker}
                      className="rounded border border-stone-200 px-2 py-0.5 font-mono text-[11px] text-stone-700 dark:border-zinc-700 dark:text-zinc-200"
                    >
                      {ticker}
                    </span>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-px bg-stone-200 dark:bg-zinc-800 lg:grid-cols-1">
                <Link
                  href="/concept"
                  className="flex items-center justify-between gap-3 bg-white px-5 py-4 text-sm font-semibold text-stone-950 transition hover:bg-stone-50 dark:bg-zinc-950 dark:text-white dark:hover:bg-zinc-900"
                >
                  <span>视觉驾驶舱</span>
                  <Gauge className="h-4 w-4 text-stone-400" />
                </Link>
                <Link
                  href={`/digest/${latest.date}`}
                  className="flex items-center justify-between gap-3 bg-white px-5 py-4 text-sm font-semibold text-stone-950 transition hover:bg-stone-50 dark:bg-zinc-950 dark:text-white dark:hover:bg-zinc-900"
                >
                  <span>原文阅读</span>
                  <BookOpenText className="h-4 w-4 text-stone-400" />
                </Link>
              </div>
            </div>
          </section>
        )}

        <section className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px]">
          <section className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                Timeline
              </p>
              <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                历史日报
              </h2>
            </div>

            <div className="divide-y divide-stone-100 dark:divide-zinc-800">
              {items.map((item) => (
                <Link
                  key={item.date}
                  href={`/digest/${item.date}`}
                  className="grid gap-4 px-5 py-4 transition hover:bg-stone-50 dark:hover:bg-zinc-900/70 lg:grid-cols-[130px_minmax(0,1fr)_180px]"
                >
                  <div>
                    <div className="font-mono text-sm font-semibold text-stone-950 dark:text-white">
                      {item.date}
                    </div>
                    <div className="mt-1 text-xs text-stone-500 dark:text-zinc-400">
                      {weekday(item.date)}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-700 dark:bg-zinc-900 dark:text-zinc-200">
                        {item.topSector || "未分类"}
                      </span>
                      {item.topTickers.slice(0, 5).map((ticker) => (
                        <span
                          key={ticker}
                          className="rounded border border-stone-200 px-2 py-0.5 font-mono text-[11px] text-stone-600 dark:border-zinc-700 dark:text-zinc-300"
                        >
                          {ticker}
                        </span>
                      ))}
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm leading-6 text-stone-600 dark:text-zinc-300">
                      {item.intro || "暂无摘要预览。"}
                    </p>
                  </div>
                  <div className="self-center">
                    <div className="mb-2 flex items-center justify-between gap-3 text-xs text-stone-500 dark:text-zinc-400">
                      <span>{item.sectorCount} 板块</span>
                      <span>{item.tickerCount} tickers</span>
                    </div>
                    <div className="h-2.5 rounded-full bg-stone-100 dark:bg-zinc-900">
                      <div
                        className="h-2.5 rounded-full bg-blue-500"
                        style={{
                          width: `${maxTickerCount === 0 ? 0 : Math.max(8, (item.tickerCount / maxTickerCount) * 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <aside className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                Ticker Memory
              </p>
              <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                连续性
              </h2>
            </div>
            <div className="p-5">
              <div className="flex flex-wrap gap-2">
                {globalTickers.slice(0, 24).map((item, idx) => (
                  <span
                    key={item.ticker}
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-xs font-semibold ${
                      idx < 6
                        ? "border-teal-200 bg-teal-50 text-teal-900 dark:border-teal-900 dark:bg-teal-950/35 dark:text-teal-100"
                        : "border-stone-200 bg-stone-50 text-stone-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                    }`}
                  >
                    {item.ticker}
                    <span className="font-sans text-[11px] tabular-nums opacity-70">
                      {item.days}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          </aside>
        </section>

        <section className="mt-6 rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <div className="border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
              Coverage Matrix
            </p>
            <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
              板块覆盖矩阵
            </h2>
          </div>

          <div className="overflow-x-auto">
            <div className="min-w-[760px]">
              <div className="grid grid-cols-[132px_repeat(7,minmax(86px,1fr))] border-b border-stone-100 px-5 py-3 text-[11px] font-semibold uppercase tracking-wide text-stone-500 dark:border-zinc-800 dark:text-zinc-400">
                <span>Date</span>
                {SECTOR_ORDER.map((sector) => (
                  <span key={sector} className="truncate px-2">
                    {sector}
                  </span>
                ))}
              </div>
              <div className="divide-y divide-stone-100 dark:divide-zinc-800">
                {items.map((item) => (
                  <div
                    key={item.date}
                    className="grid grid-cols-[132px_repeat(7,minmax(86px,1fr))] items-center px-5 py-3"
                  >
                    <Link
                      href={`/digest/${item.date}`}
                      className="font-mono text-xs font-semibold text-stone-950 hover:text-blue-700 dark:text-white dark:hover:text-blue-300"
                    >
                      {item.date}
                    </Link>
                    {SECTOR_ORDER.map((sector, idx) => {
                      const active = item.sectorNames.includes(sector);
                      return (
                        <span key={sector} className="px-2">
                          <span
                            className={`block h-3 rounded-full ${
                              active
                                ? matrixColors[idx % matrixColors.length]
                                : "bg-stone-100 dark:bg-zinc-900"
                            }`}
                          />
                        </span>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function MetricTile({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-4 py-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-[0.16em] text-stone-500 dark:text-zinc-400">
          {label}
        </span>
        <span className="text-stone-400">{icon}</span>
      </div>
      <div className="mt-2 truncate text-2xl font-semibold tabular-nums text-stone-950 dark:text-white">
        {value}
      </div>
      <div className="mt-1 truncate text-xs text-stone-500 dark:text-zinc-400">
        {detail}
      </div>
    </div>
  );
}

function toArchiveDigest(
  summary: Awaited<ReturnType<typeof listDigests>>[number],
  digest: Digest
): ArchiveDigest {
  const sectorCounts = digest.sectors
    .map((sector) => ({
      name: sector.name,
      count: sector.subsections.filter((sub) => sub.heading || sub.bodyMd)
        .length,
    }))
    .sort((a, b) => b.count - a.count);
  const tickerCounts = tickerCountMap(digest);
  const topTickers = Array.from(tickerCounts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([ticker]) => ticker);

  return {
    date: summary.date,
    intro: summary.intro,
    sectorCount: summary.sectorCount,
    tickerCount: summary.tickerCount,
    topSector: sectorCounts[0]?.name ?? "",
    topSectorCount: sectorCounts[0]?.count ?? 0,
    topTickers,
    sectorNames: digest.sectors.map((sector) => sector.name),
    imageCount: countImages(digest),
  };
}

function tickerCountMap(digest: Digest): Map<string, number> {
  const counts = new Map<string, number>();
  for (const sector of digest.sectors) {
    for (const sub of sector.subsections) {
      for (const ticker of sub.allTickers) {
        counts.set(ticker, (counts.get(ticker) ?? 0) + 1);
      }
    }
  }
  return counts;
}

function buildGlobalTickers(digests: Digest[]) {
  const counts = new Map<string, { days: Set<string>; mentions: number }>();
  for (const digest of digests) {
    const perDigest = tickerCountMap(digest);
    for (const [ticker, count] of perDigest) {
      const current =
        counts.get(ticker) ?? { days: new Set<string>(), mentions: 0 };
      current.days.add(digest.date);
      current.mentions += count;
      counts.set(ticker, current);
    }
  }
  return Array.from(counts.entries())
    .map(([ticker, value]) => ({
      ticker,
      days: value.days.size,
      mentions: value.mentions,
    }))
    .sort(
      (a, b) =>
        b.days - a.days || b.mentions - a.mentions || a.ticker.localeCompare(b.ticker)
    );
}

function countImages(digest: Digest): number {
  const body = [
    digest.intro,
    digest.calendar ?? "",
    ...digest.sectors.flatMap((sector) =>
      sector.subsections.map((sub) => sub.bodyMd)
    ),
  ].join("\n");
  return (body.match(/!\[[^\]]*]\([^)]+\)/g) ?? []).length;
}

function weekday(date: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    weekday: "long",
    timeZone: "UTC",
  }).format(new Date(`${date}T00:00:00Z`));
}
