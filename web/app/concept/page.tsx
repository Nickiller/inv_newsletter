import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  BookOpenText,
  CalendarDays,
  Gauge,
  Layers3,
  Network,
  Radar,
  Tags,
} from "lucide-react";
import { listDigests, loadDigest } from "@/lib/digests";
import type { Digest, Sector, Subsection } from "@/lib/parser";

export const dynamic = "force-dynamic";

type Story = {
  id: string;
  sector: string;
  heading: string;
  summary: string;
  tickers: string[];
};

type SectorStat = {
  name: string;
  index: number;
  count: number;
  tickerCount: number;
  tickers: string[];
  share: number;
  topStories: Story[];
};

type TickerStat = {
  ticker: string;
  count: number;
  sectors: string[];
};

type SignalBucket = {
  label: string;
  count: number;
  color: string;
};

const palette = [
  {
    chip: "bg-teal-600 text-white",
    soft: "bg-teal-50 text-teal-900 border-teal-200 dark:bg-teal-950/35 dark:text-teal-100 dark:border-teal-900",
    line: "bg-teal-600",
  },
  {
    chip: "bg-blue-600 text-white",
    soft: "bg-blue-50 text-blue-900 border-blue-200 dark:bg-blue-950/35 dark:text-blue-100 dark:border-blue-900",
    line: "bg-blue-600",
  },
  {
    chip: "bg-amber-500 text-white",
    soft: "bg-amber-50 text-amber-950 border-amber-200 dark:bg-amber-950/35 dark:text-amber-100 dark:border-amber-900",
    line: "bg-amber-500",
  },
  {
    chip: "bg-rose-600 text-white",
    soft: "bg-rose-50 text-rose-950 border-rose-200 dark:bg-rose-950/35 dark:text-rose-100 dark:border-rose-900",
    line: "bg-rose-600",
  },
  {
    chip: "bg-emerald-600 text-white",
    soft: "bg-emerald-50 text-emerald-950 border-emerald-200 dark:bg-emerald-950/35 dark:text-emerald-100 dark:border-emerald-900",
    line: "bg-emerald-600",
  },
  {
    chip: "bg-violet-600 text-white",
    soft: "bg-violet-50 text-violet-950 border-violet-200 dark:bg-violet-950/35 dark:text-violet-100 dark:border-violet-900",
    line: "bg-violet-600",
  },
];

const signalRules = [
  {
    label: "业绩/指引",
    color: "bg-emerald-500",
    words: [
      "财报",
      "业绩",
      "营收",
      "利润",
      "盈利",
      "指引",
      "EPS",
      "revenue",
      "margin",
    ],
  },
  {
    label: "产品/技术",
    color: "bg-blue-500",
    words: [
      "模型",
      "产品",
      "发布",
      "平台",
      "芯片",
      "GPU",
      "AI",
      "agent",
      "cloud",
    ],
  },
  {
    label: "需求/订单",
    color: "bg-teal-500",
    words: [
      "需求",
      "订单",
      "客户",
      "采用",
      "增长",
      "渗透",
      "订阅",
      "pipeline",
    ],
  },
  {
    label: "竞争/监管",
    color: "bg-rose-500",
    words: [
      "竞争",
      "监管",
      "反垄断",
      "政策",
      "关税",
      "诉讼",
      "风险",
      "限制",
    ],
  },
  {
    label: "估值/资本",
    color: "bg-amber-500",
    words: [
      "估值",
      "目标价",
      "上调",
      "下调",
      "评级",
      "回购",
      "资本",
      "倍数",
      "valuation",
    ],
  },
];

export default async function VisualConceptPage() {
  const digests = await listDigests();
  const latest = digests[0];
  const digest = latest ? await loadDigest(latest.date) : null;

  if (!digest) {
    return (
      <main className="min-h-screen bg-stone-50 px-6 py-10 text-stone-950 dark:bg-zinc-950 dark:text-zinc-50">
        <div className="mx-auto max-w-3xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/35 dark:text-amber-100">
          没有找到可用于视觉预览的 daily digest。请确认{" "}
          <code className="rounded bg-amber-100 px-1 dark:bg-amber-900/60">
            ../output/daily
          </code>{" "}
          下存在摘要文件。
        </div>
      </main>
    );
  }

  const model = buildViewModel(digest);

  return (
    <main className="min-h-screen bg-[#f6f7f2] text-stone-950 dark:bg-[#101312] dark:text-stone-100">
      <header className="sticky top-0 z-30 border-b border-stone-200 bg-[#f6f7f2]/92 backdrop-blur-md dark:border-zinc-800 dark:bg-[#101312]/92">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-medium text-stone-700 transition hover:border-stone-400 hover:text-stone-950 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-500 dark:hover:text-white"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="hidden sm:inline">日期列表</span>
          </Link>

          <div className="min-w-0 text-center">
            <div className="truncate text-sm font-semibold uppercase tracking-[0.16em] text-stone-500 dark:text-zinc-400">
              Investment Daily Console
            </div>
            <h1 className="truncate text-base font-semibold text-stone-950 dark:text-white">
              {digest.date}
            </h1>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/concept/archive"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-medium text-stone-700 transition hover:border-stone-400 hover:text-stone-950 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-500 dark:hover:text-white"
            >
              <CalendarDays className="h-4 w-4" />
              <span className="hidden sm:inline">列表</span>
            </Link>
            <Link
              href={`/digest/${digest.date}`}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-stone-950 px-3 text-sm font-medium text-white transition hover:bg-stone-800 dark:bg-zinc-50 dark:text-zinc-950 dark:hover:bg-zinc-200"
            >
              <BookOpenText className="h-4 w-4" />
              <span className="hidden sm:inline">原文</span>
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:py-8">
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile
            icon={<Layers3 className="h-4 w-4" />}
            label="板块"
            value={String(model.sectorStats.length)}
            detail={`${model.totalStories} 条摘要`}
          />
          <MetricTile
            icon={<Tags className="h-4 w-4" />}
            label="Ticker"
            value={String(model.tickerStats.length)}
            detail={`${model.crossSectorTickers.length} 个跨板块`}
          />
          <MetricTile
            icon={<Activity className="h-4 w-4" />}
            label="最高关注"
            value={model.topTicker?.ticker ?? "-"}
            detail={
              model.topTicker
                ? `${model.topTicker.count} 次 / ${model.topTicker.sectors.length} 板块`
                : "暂无"
            }
          />
          <MetricTile
            icon={<Gauge className="h-4 w-4" />}
            label="图表线索"
            value={String(model.imageCount)}
            detail={model.calendarLines.length > 0 ? "含催化剂日历" : "无日历"}
          />
        </section>

        <section className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.9fr)]">
          <section className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-center justify-between gap-3 border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                  Main Narrative
                </p>
                <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                  今日主线
                </h2>
              </div>
              <Radar className="h-5 w-5 text-stone-400" />
            </div>

            <div className="grid gap-px bg-stone-200 dark:bg-zinc-800 md:grid-cols-3">
              {model.sectorStats.slice(0, 3).map((sector, idx) => {
                const colors = palette[idx % palette.length];
                return (
                  <article
                    key={sector.name}
                    className="bg-white p-5 dark:bg-zinc-950"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <span
                          className={`inline-flex rounded px-2 py-1 text-[11px] font-semibold ${colors.chip}`}
                        >
                          #{idx + 1}
                        </span>
                        <h3 className="mt-3 min-h-12 text-lg font-semibold leading-snug text-stone-950 dark:text-white">
                          {sector.name}
                        </h3>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="text-2xl font-semibold tabular-nums">
                          {sector.count}
                        </div>
                        <div className="text-xs text-stone-500 dark:text-zinc-400">
                          条
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 h-2 rounded-full bg-stone-100 dark:bg-zinc-900">
                      <div
                        className={`h-2 rounded-full ${colors.line}`}
                        style={{ width: `${Math.max(10, sector.share)}%` }}
                      />
                    </div>

                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {sector.tickers.slice(0, 5).map((ticker) => (
                        <span
                          key={ticker}
                          className="rounded border border-stone-200 px-2 py-0.5 font-mono text-[11px] text-stone-700 dark:border-zinc-700 dark:text-zinc-200"
                        >
                          {ticker}
                        </span>
                      ))}
                    </div>

                    <ul className="mt-5 space-y-3">
                      {sector.topStories.slice(0, 2).map((story) => (
                        <li
                          key={story.id}
                          className="border-t border-stone-100 pt-3 dark:border-zinc-800"
                        >
                          <Link
                            href={`/digest/${digest.date}#${story.id}`}
                            className="line-clamp-2 text-sm font-medium leading-5 text-stone-900 hover:text-blue-700 dark:text-zinc-100 dark:hover:text-blue-300"
                          >
                            {story.heading || story.summary}
                          </Link>
                          {story.summary && (
                            <p className="mt-1 line-clamp-2 text-xs leading-5 text-stone-500 dark:text-zinc-400">
                              {story.summary}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  </article>
                );
              })}
            </div>
          </section>

          <aside className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-center justify-between gap-3 border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                  Attention Stack
                </p>
                <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                  Ticker 热度
                </h2>
              </div>
              <Network className="h-5 w-5 text-stone-400" />
            </div>

            <div className="p-5">
              <div className="flex flex-wrap gap-2">
                {model.tickerStats.slice(0, 18).map((ticker, idx) => {
                  const rankSize =
                    idx < 3
                      ? "text-base px-3 py-1.5"
                      : idx < 9
                        ? "text-sm px-2.5 py-1"
                        : "text-xs px-2 py-0.5";
                  const colors = palette[idx % palette.length];
                  return (
                    <span
                      key={ticker.ticker}
                      title={`${ticker.sectors.join(" / ")} · ${ticker.count} 次`}
                      className={`inline-flex items-center gap-1.5 rounded-md border font-mono font-semibold ${rankSize} ${colors.soft}`}
                    >
                      {ticker.ticker}
                      <span className="font-sans text-[11px] tabular-nums opacity-70">
                        {ticker.count}
                      </span>
                    </span>
                  );
                })}
              </div>

              <div className="mt-6 space-y-3">
                {model.crossSectorTickers.slice(0, 5).map((ticker) => (
                  <div
                    key={ticker.ticker}
                    className="grid grid-cols-[72px_minmax(0,1fr)_32px] items-center gap-3 border-t border-stone-100 pt-3 dark:border-zinc-800"
                  >
                    <span className="font-mono text-sm font-semibold text-stone-950 dark:text-white">
                      {ticker.ticker}
                    </span>
                    <span className="truncate text-xs text-stone-500 dark:text-zinc-400">
                      {ticker.sectors.join(" / ")}
                    </span>
                    <span className="text-right text-sm font-semibold tabular-nums">
                      {ticker.count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </section>

        <section className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                Sector Heatmap
              </p>
              <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                板块信号分布
              </h2>
            </div>

            <div className="divide-y divide-stone-100 dark:divide-zinc-800">
              {model.sectorStats.map((sector, idx) => {
                const colors = palette[idx % palette.length];
                return (
                  <Link
                    key={sector.name}
                    href={`/digest/${digest.date}#sector-${sector.index}`}
                    className="grid gap-3 px-5 py-4 transition hover:bg-stone-50 dark:hover:bg-zinc-900/70 md:grid-cols-[180px_minmax(0,1fr)_110px]"
                  >
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold text-stone-950 dark:text-white">
                        {sector.name}
                      </h3>
                      <p className="mt-1 text-xs text-stone-500 dark:text-zinc-400">
                        {sector.tickerCount} tickers
                      </p>
                    </div>
                    <div className="self-center">
                      <div className="h-3 rounded-full bg-stone-100 dark:bg-zinc-900">
                        <div
                          className={`h-3 rounded-full ${colors.line}`}
                          style={{ width: `${Math.max(5, sector.share)}%` }}
                        />
                      </div>
                      <div className="mt-2 flex min-h-5 flex-wrap gap-1">
                        {sector.tickers.slice(0, 7).map((ticker) => (
                          <span
                            key={ticker}
                            className="font-mono text-[11px] text-stone-500 dark:text-zinc-400"
                          >
                            {ticker}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center justify-start gap-2 md:justify-end">
                      <span className="text-2xl font-semibold tabular-nums text-stone-950 dark:text-white">
                        {sector.count}
                      </span>
                      <span className="text-xs text-stone-500 dark:text-zinc-400">
                        条
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>

          <section className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                Signal Mix
              </p>
              <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                主题成分
              </h2>
            </div>

            <div className="space-y-4 p-5">
              {model.signalBuckets.map((bucket) => (
                <div key={bucket.label}>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-stone-800 dark:text-zinc-100">
                      {bucket.label}
                    </span>
                    <span className="text-sm font-semibold tabular-nums text-stone-950 dark:text-white">
                      {bucket.count}
                    </span>
                  </div>
                  <div className="h-2.5 rounded-full bg-stone-100 dark:bg-zinc-900">
                    <div
                      className={`h-2.5 rounded-full ${bucket.color}`}
                      style={{
                        width: `${model.maxBucketCount === 0 ? 0 : Math.max(8, (bucket.count / model.maxBucketCount) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>
        </section>

        <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
          <section className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                Reading Queue
              </p>
              <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                重点阅读队列
              </h2>
            </div>

            <div className="divide-y divide-stone-100 dark:divide-zinc-800">
              {model.stories.slice(0, 8).map((story, idx) => (
                <Link
                  key={story.id}
                  href={`/digest/${digest.date}#${story.id}`}
                  className="grid gap-3 px-5 py-4 transition hover:bg-stone-50 dark:hover:bg-zinc-900/70 sm:grid-cols-[32px_minmax(0,1fr)_minmax(120px,180px)]"
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-md bg-stone-100 text-xs font-semibold tabular-nums text-stone-600 dark:bg-zinc-900 dark:text-zinc-300">
                    {idx + 1}
                  </span>
                  <div className="min-w-0">
                    <h3 className="line-clamp-2 text-sm font-semibold leading-5 text-stone-950 dark:text-white">
                      {story.heading || story.summary}
                    </h3>
                    {story.summary && (
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-stone-500 dark:text-zinc-400">
                        {story.summary}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap content-start gap-1.5 sm:justify-end">
                    {story.tickers.slice(0, 4).map((ticker) => (
                      <span
                        key={ticker}
                        className="rounded border border-stone-200 px-2 py-0.5 font-mono text-[11px] text-stone-700 dark:border-zinc-700 dark:text-zinc-200"
                      >
                        {ticker}
                      </span>
                    ))}
                    <span className="rounded border border-stone-200 px-2 py-0.5 text-[11px] text-stone-500 dark:border-zinc-700 dark:text-zinc-400">
                      {story.sector}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <aside className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-center justify-between gap-3 border-b border-stone-200 px-5 py-4 dark:border-zinc-800">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-zinc-400">
                  Catalyst Tape
                </p>
                <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-white">
                  催化剂
                </h2>
              </div>
              <CalendarDays className="h-5 w-5 text-stone-400" />
            </div>

            <div className="p-5">
              {model.calendarLines.length === 0 ? (
                <p className="text-sm text-stone-500 dark:text-zinc-400">
                  暂无日历条目。
                </p>
              ) : (
                <ol className="space-y-4">
                  {model.calendarLines.slice(0, 7).map((line, idx) => (
                    <li
                      key={`${line}-${idx}`}
                      className="grid grid-cols-[28px_minmax(0,1fr)] gap-3"
                    >
                      <span className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md bg-stone-950 text-xs font-semibold text-white dark:bg-zinc-50 dark:text-zinc-950">
                        {idx + 1}
                      </span>
                      <p className="text-sm leading-6 text-stone-700 dark:text-zinc-200">
                        {line}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </aside>
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

function buildViewModel(digest: Digest) {
  const stories = flattenStories(digest.sectors);
  const totalStories = stories.length;
  const sectorStats = buildSectorStats(digest.sectors, totalStories);
  const tickerStats = buildTickerStats(stories);
  const signalBuckets = buildSignalBuckets(stories);
  const maxBucketCount = Math.max(0, ...signalBuckets.map((b) => b.count));
  const imageCount = countImages(digest);
  const calendarLines = parseCalendarLines(digest.calendar);

  return {
    stories,
    sectorStats,
    tickerStats,
    topTicker: tickerStats[0],
    crossSectorTickers: tickerStats.filter((t) => t.sectors.length > 1),
    signalBuckets,
    maxBucketCount,
    totalStories,
    imageCount,
    calendarLines,
  };
}

function buildSectorStats(sectors: Sector[], totalStories: number): SectorStat[] {
  return sectors
    .map((sector, index) => {
      const stories = sector.subsections
        .filter((sub) => sub.heading || sub.bodyMd)
        .map((sub) => toStory(sector.name, sub));
      const tickerSet = new Set<string>();
      for (const story of stories) {
        for (const ticker of story.tickers) tickerSet.add(ticker);
      }
      return {
        name: sector.name,
        index,
        count: stories.length,
        tickerCount: tickerSet.size,
        tickers: Array.from(tickerSet).sort(),
        share: totalStories === 0 ? 0 : (stories.length / totalStories) * 100,
        topStories: stories,
      };
    })
    .filter((stat) => stat.count > 0)
    .sort((a, b) => b.count - a.count);
}

function buildTickerStats(stories: Story[]): TickerStat[] {
  const byTicker = new Map<string, { count: number; sectors: Set<string> }>();
  for (const story of stories) {
    for (const ticker of story.tickers) {
      const current =
        byTicker.get(ticker) ?? { count: 0, sectors: new Set<string>() };
      current.count += 1;
      current.sectors.add(story.sector);
      byTicker.set(ticker, current);
    }
  }

  return Array.from(byTicker.entries())
    .map(([ticker, value]) => ({
      ticker,
      count: value.count,
      sectors: Array.from(value.sectors).sort(),
    }))
    .sort(
      (a, b) =>
        b.count - a.count ||
        b.sectors.length - a.sectors.length ||
        a.ticker.localeCompare(b.ticker)
    );
}

function buildSignalBuckets(stories: Story[]): SignalBucket[] {
  return signalRules.map((rule) => {
    const count = stories.reduce((sum, story) => {
      const text = `${story.heading}\n${story.summary}`.toLowerCase();
      const hit = rule.words.some((word) => text.includes(word.toLowerCase()));
      return sum + (hit ? 1 : 0);
    }, 0);
    return { label: rule.label, count, color: rule.color };
  });
}

function flattenStories(sectors: Sector[]): Story[] {
  return sectors.flatMap((sector) =>
    sector.subsections
      .filter((sub) => sub.heading || sub.bodyMd)
      .map((sub) => toStory(sector.name, sub))
  );
}

function toStory(sector: string, sub: Subsection): Story {
  return {
    id: sub.id,
    sector,
    heading: sub.heading,
    summary: summarizeMarkdown(sub.bodyMd),
    tickers: sub.allTickers,
  };
}

function summarizeMarkdown(markdown: string): string {
  const cleaned = markdown
    .replace(/!\[[^\]]*]\([^)]+\)/g, "")
    .replace(/\[[^\]]+]\([^)]+\)/g, (match) => match.replace(/^\[|\]\([^)]+\)$/g, ""))
    .replace(/^#+\s+/gm, "")
    .replace(/^[>\-*+\d.)\s]+/gm, "")
    .replace(/\|/g, " ")
    .replace(/\*\*|__|`/g, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .find((line) => line.length > 12);

  if (!cleaned) return "";
  return cleaned.length > 108 ? `${cleaned.slice(0, 108)}...` : cleaned;
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

function parseCalendarLines(calendar: string | null): string[] {
  if (!calendar) return [];
  return calendar
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^#+\s*/, "")
        .replace(/^[>\-*+\d.)\s]+/, "")
        .trim()
    )
    .filter((line) => line && !line.includes("本周关注催化剂"))
    .slice(0, 12);
}
