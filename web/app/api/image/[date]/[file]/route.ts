import { promises as fs } from "node:fs";
import path from "node:path";
import { getOutputDir } from "@/lib/digests";

const MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
};

export async function GET(
  _req: Request,
  ctx: RouteContext<"/api/image/[date]/[file]">
) {
  const { date, file } = await ctx.params;

  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return new Response("bad date", { status: 400 });
  }
  // Reject path traversal: file must not contain separators
  if (file.includes("/") || file.includes("\\") || file.includes("..")) {
    return new Response("bad file", { status: 400 });
  }

  const ext = path.extname(file).toLowerCase();
  const mime = MIME[ext];
  if (!mime) return new Response("unsupported type", { status: 415 });

  const filePath = path.join(getOutputDir(), date, file);
  let data: Buffer;
  try {
    data = await fs.readFile(filePath);
  } catch {
    return new Response("not found", { status: 404 });
  }

  return new Response(new Uint8Array(data), {
    status: 200,
    headers: {
      "Content-Type": mime,
      "Cache-Control": "public, max-age=3600",
    },
  });
}
