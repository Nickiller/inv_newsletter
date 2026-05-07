"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";

type Props = {
  date: string;
  markdown: string;
};

const SOURCE_PREFIX = /^来源[：:]\s*/;

function flattenChildren(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(flattenChildren).join("");
  return "";
}

// Rewrites relative image paths in markdown so they hit the image API route.
// Source markdown uses paths like "2026-05-01/IMG_03.png".
function rewriteImageSrc(date: string, src: string): string {
  if (!src) return src;
  if (/^(https?:|data:|\/)/.test(src)) return src;
  const cleaned = src.replace(/^\.\//, "");
  // If already prefixed with the date dir, strip it (we'll re-add via API)
  const noDatePrefix = cleaned.startsWith(`${date}/`)
    ? cleaned.slice(date.length + 1)
    : cleaned;
  // Only forward the basename; reject anything that tries to traverse
  const safe = noDatePrefix.split("/").pop() ?? "";
  return `/api/image/${date}/${encodeURIComponent(safe)}`;
}

export default function MarkdownSection({ date, markdown }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSlug]}
      components={{
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        img: ({ src, alt, ...rest }: any) => {
          const rewritten = rewriteImageSrc(date, String(src ?? ""));
          // eslint-disable-next-line @next/next/no-img-element
          return <img src={rewritten} alt={alt ?? ""} loading="lazy" {...rest} />;
        },
        a: ({ href, children, ...rest }) => {
          const isExternal = !!href && /^https?:/.test(href);
          return (
            <a
              href={href}
              target={isExternal ? "_blank" : undefined}
              rel={isExternal ? "noopener noreferrer" : undefined}
              {...rest}
            >
              {children}
            </a>
          );
        },
        em: ({ children, ...rest }) => {
          // "*来源：XXX*" attribution markers render as non-clickable chips.
          // Clickable behaviour only applies when the source markdown has a
          // specific report URL — those go through the <a> renderer above and
          // pick up the chip styling via `li a[href^="http"]` in globals.css.
          const text = flattenChildren(children);
          if (!SOURCE_PREFIX.test(text)) {
            return <em {...rest}>{children}</em>;
          }
          return <span className="source-attr">{children}</span>;
        },
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}
