import type { Obs } from "@/lib/data";

export function Sparkline({ series, label }: { series: Obs[]; label: string }) {
  const points = series.filter((o) => o.value !== null) as { obs_date: string; value: number }[];
  if (points.length < 2) return null;
  const w = 240;
  const h = 48;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const d = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - 4 - ((p.value - min) / span) * (h - 8);
      return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-12 text-accent" role="img" aria-label={label}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
