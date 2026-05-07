import Link from "next/link";
import { listDigests } from "@/lib/digests";
import { ThemeToggle } from "@/components/ThemeToggle";
import { listAvailableEntities } from "@/lib/timeline";

export const dynamic = "force-dynamic";

export default async function Home() {
  const digests = await listDigests();
  const entities = listAvailableEntities();

  return (
    <main className="reader-shell min-h-screen">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <header className="mb-10 flex items-start justify-between gap-4">
          <div>
            <h1 className="reader-title text-[34px] leading-tight text-foreground">
              Daily Research Digest
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              按板块 / Ticker 过滤每日研报摘要
            </p>
          </div>
          <ThemeToggle />
        </header>

        {entities.length > 0 && (
          <section className="mb-10">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              实体时间线
            </div>
            <div className="flex flex-wrap gap-2">
              {entities.map((e) => (
                <Link
                  key={e.id}
                  href={`/entity/${e.id}`}
                  className="rounded-full border border-border bg-card px-3 py-1 text-sm text-foreground transition hover:border-primary hover:text-primary"
                >
                  {e.name}
                </Link>
              ))}
            </div>
          </section>
        )}

        {digests.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-card px-4 py-3 text-sm text-muted-foreground">
            没有找到 daily digest。检查{" "}
            <code className="rounded bg-muted px-1 font-mono text-foreground">
              ../output/daily/*_daily_digest.md
            </code>{" "}
            是否存在，或设置环境变量{" "}
            <code className="rounded bg-muted px-1 font-mono text-foreground">
              INV_OUTPUT_DIR
            </code>
            。
          </div>
        ) : (
          <ul className="space-y-2">
            {digests.map((d) => (
              <li key={d.date}>
                <Link
                  href={`/digest/${d.date}`}
                  className="block rounded-lg border border-border bg-card px-4 py-3 transition hover:border-primary hover:shadow-sm"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-mono text-sm font-semibold text-primary">
                      {d.date}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {d.sectorCount} 板块 · {d.tickerCount} tickers
                    </span>
                  </div>
                  {d.intro && (
                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                      {d.intro}
                    </p>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
