"use client";

import { useMemo, useState } from "react";
import type { EquityPoint } from "@/lib/api";
import { istTime, money } from "@/lib/format";

/** Lightweight SVG equity curve with a baseline at starting capital. */
export default function EquityChart({ points, initial }: { points: EquityPoint[]; initial: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 800, H = 240, P = 8;

  const geo = useMemo(() => {
    if (points.length < 2) return null;
    const vals = points.map((p) => p.equity);
    const min = Math.min(initial, ...vals), max = Math.max(initial, ...vals);
    const span = max - min || 1;
    const x = (i: number) => P + (i / (points.length - 1)) * (W - 2 * P);
    const y = (v: number) => P + (1 - (v - min) / span) * (H - 2 * P);
    const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join("");
    return { x, y, d, base: y(initial) };
  }, [points, initial]);

  if (!geo) return <div className="empty">Not enough data for a chart yet.</div>;

  const last = points[points.length - 1].equity;
  const up = last >= initial;
  const h = hover != null ? points[hover] : null;

  return (
    <div className="chart">
      <div className="chart-readout">
        {h ? (
          <>
            <strong>{money(h.equity)}</strong> <span className="muted">{istTime(h.ts)}</span>
          </>
        ) : (
          <span className="muted">Equity curve · hover or tap to inspect</span>
        )}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Equity curve"
        onMouseLeave={() => setHover(null)}
        onPointerMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const i = Math.round(((e.clientX - r.left) / r.width) * (points.length - 1));
          setHover(Math.max(0, Math.min(points.length - 1, i)));
        }}
      >
        <line x1={P} x2={W - P} y1={geo.base} y2={geo.base} className="chart-base" />
        <path d={geo.d} className={`chart-line ${up ? "up" : "down"}`} vectorEffect="non-scaling-stroke" />
        {hover != null && (
          <line x1={geo.x(hover)} x2={geo.x(hover)} y1={P} y2={H - P} className="chart-cursor" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
    </div>
  );
}
