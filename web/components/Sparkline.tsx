type Props = {
  /** values aligned with `dates` (or just one-per-bucket) */
  values: number[];
  width?: number;
  height?: number;
  className?: string;
  ariaLabel?: string;
};

export function Sparkline({
  values,
  width = 200,
  height = 50,
  className,
  ariaLabel,
}: Props) {
  if (values.length < 2) {
    return <svg width={width} height={height} className={className} aria-hidden />;
  }
  const pad = 4;
  const max = Math.max(...values, 1);
  const stepX = (width - pad * 2) / (values.length - 1);
  const points = values.map((v, i) => [
    pad + i * stepX,
    height - pad - (v / max) * (height - pad * 2),
  ] as const);
  const path = "M" + points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-label={ariaLabel}
      role={ariaLabel ? "img" : undefined}
    >
      <line
        x1={pad}
        y1={height - pad}
        x2={width - pad}
        y2={height - pad}
        className="stroke-border"
        strokeWidth="1"
      />
      <path d={path} className="stroke-primary" strokeWidth="1.6" fill="none" />
      {points.map(([x, y], i) =>
        values[i] > 0 ? (
          <circle key={i} cx={x.toFixed(1)} cy={y.toFixed(1)} r="2" className="fill-primary" />
        ) : null
      )}
    </svg>
  );
}
