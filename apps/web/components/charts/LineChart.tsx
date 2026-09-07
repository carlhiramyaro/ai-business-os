"use client";

import { useState } from "react";
import { niceMax } from "./scale";

export interface RevenuePoint {
  date: string; // ISO date
  revenue: number;
}

const WIDTH = 640;
const HEIGHT = 220;
const PAD = { top: 12, right: 12, bottom: 28, left: 56 };
const INNER_WIDTH = WIDTH - PAD.left - PAD.right;
const INNER_HEIGHT = HEIGHT - PAD.top - PAD.bottom;

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Trend over time -> line, per the dataviz skill's form table. Dense
// enough that per-point labels would be noise, so only the endpoints and
// the peak are direct-labeled; everything else lives behind the hover
// crosshair + tooltip, which is the deliverable here, not an upgrade.
export function LineChart({ points, format }: { points: RevenuePoint[]; format: (value: number) => string }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (points.length === 0) {
    return <p className="text-sm text-muted">No sales recorded in this period.</p>;
  }

  const timestamps = points.map((p) => new Date(p.date).getTime());
  const minDate = Math.min(...timestamps);
  const maxDate = Math.max(...timestamps);
  const maxRevenue = niceMax(Math.max(...points.map((p) => p.revenue)));

  const xForTime = (t: number) =>
    maxDate === minDate ? PAD.left + INNER_WIDTH / 2 : PAD.left + ((t - minDate) / (maxDate - minDate)) * INNER_WIDTH;
  const yForValue = (v: number) => PAD.top + INNER_HEIGHT - (v / maxRevenue) * INNER_HEIGHT;

  const coords = points.map((p, i) => ({ x: xForTime(timestamps[i]), y: yForValue(p.revenue), point: p }));
  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");

  const peakIndex = points.reduce((best, p, i) => (p.revenue > points[best].revenue ? i : best), 0);
  const labeledIndices = new Set([0, points.length - 1, peakIndex]);
  const yTicks = [0, maxRevenue / 2, maxRevenue];

  function handleMove(event: React.PointerEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * INNER_WIDTH + PAD.left;
    let nearest = 0;
    let nearestDist = Infinity;
    coords.forEach((c, i) => {
      const dist = Math.abs(c.x - relX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIndex(nearest);
  }

  const hovered = hoverIndex != null ? coords[hoverIndex] : null;

  return (
    <div className="relative w-full">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="Daily revenue">
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yForValue(tick)}
              y2={yForValue(tick)}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text x={PAD.left - 8} y={yForValue(tick)} textAnchor="end" dominantBaseline="middle" className="fill-muted" fontSize={10}>
              {format(tick)}
            </text>
          </g>
        ))}

        <text x={PAD.left} y={HEIGHT - 8} textAnchor="start" className="fill-muted" fontSize={10}>
          {shortDate(points[0].date)}
        </text>
        <text x={WIDTH - PAD.right} y={HEIGHT - 8} textAnchor="end" className="fill-muted" fontSize={10}>
          {shortDate(points[points.length - 1].date)}
        </text>

        <path d={path} fill="none" stroke="var(--brand)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {coords.map((c, i) =>
          labeledIndices.has(i) ? (
            <g key={i}>
              <circle cx={c.x} cy={c.y} r={5} fill="var(--brand)" stroke="var(--surface)" strokeWidth={2} />
              <text
                x={c.x}
                y={c.y - 10}
                textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
                className="fill-foreground font-semibold"
                fontSize={10}
              >
                {format(c.point.revenue)}
              </text>
            </g>
          ) : null
        )}

        {hovered && (
          <g pointerEvents="none">
            <line x1={hovered.x} x2={hovered.x} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="var(--border)" strokeWidth={1} />
            <circle cx={hovered.x} cy={hovered.y} r={5} fill="var(--brand)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}

        <rect
          x={PAD.left}
          y={PAD.top}
          width={INNER_WIDTH}
          height={INNER_HEIGHT}
          fill="transparent"
          onPointerMove={handleMove}
          onPointerLeave={() => setHoverIndex(null)}
        />
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm"
          style={{ left: `${(hovered.x / WIDTH) * 100}%`, top: `${(hovered.y / HEIGHT) * 100}%` }}
        >
          <div className="font-medium tabular-nums text-foreground">{format(hovered.point.revenue)}</div>
          <div className="text-muted">{shortDate(hovered.point.date)}</div>
        </div>
      )}
    </div>
  );
}
