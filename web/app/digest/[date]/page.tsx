import Link from "next/link";
import { notFound } from "next/navigation";
import { listDigests, loadDigest } from "@/lib/digests";
import { allTickers } from "@/lib/parser";
import DigestView from "@/components/DigestView";
import DateSwitcher from "@/components/DateSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";

export const dynamic = "force-dynamic";

export default async function DigestPage(
  props: PageProps<"/digest/[date]">
) {
  const { date } = await props.params;
  const [digest, allDigests] = await Promise.all([
    loadDigest(date),
    listDigests(),
  ]);
  if (!digest) notFound();

  const tickers = allTickers(digest);
  const dateList = allDigests.map((d) => d.date);

  return (
    <main className="reader-shell min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3.5">
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← 全部日期
          </Link>
          <h1 className="reader-title flex items-center gap-2 text-[17px] text-foreground">
            <span>Daily Research Digest</span>
            <span className="text-muted-foreground/60">·</span>
            <DateSwitcher current={digest.date} dates={dateList} />
          </h1>
          <div className="flex w-20 justify-end">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <DigestView digest={digest} allTickers={tickers} />
    </main>
  );
}
