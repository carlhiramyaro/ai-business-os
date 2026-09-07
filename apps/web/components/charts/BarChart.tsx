// "Compare magnitude" per the dataviz skill's form table -- sequential
// color (one hue, more-is-darker), applied ordinally by rank since these
// rows are already sorted by magnitude. Identity comes from the direct
// label beside each bar, not from a categorical hue per row.
const RANK_COLORS = ["var(--chart-4)", "var(--chart-3)", "var(--chart-2)", "var(--chart-1)"];
const OTHER_COLOR = "var(--chart-other)";
const MAX_BARS = 4;

export interface BarChartItem {
  label: string;
  value: number;
}

export function BarChart({ items, format }: { items: BarChartItem[]; format: (value: number) => string }) {
  if (items.length === 0) return null;

  const sorted = [...items].sort((a, b) => b.value - a.value);
  const top = sorted.slice(0, MAX_BARS);
  const rest = sorted.slice(MAX_BARS);
  const restTotal = rest.reduce((sum, item) => sum + item.value, 0);
  const rows = restTotal > 0 ? [...top, { label: "Other", value: restTotal }] : top;
  const max = Math.max(...rows.map((row) => row.value), 1);

  return (
    <div className="flex flex-col gap-2">
      {rows.map((row, index) => (
        <div key={row.label} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="min-w-0 truncate text-muted">{row.label}</span>
            <span className="shrink-0 font-medium tabular-nums text-foreground">{format(row.value)}</span>
          </div>
          <div className="h-3 w-full rounded-sm bg-chart-track">
            <div
              className="h-full rounded-r"
              style={{
                width: `${Math.max(0, row.value / max) * 100}%`,
                backgroundColor: index < top.length ? RANK_COLORS[index] : OTHER_COLOR,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
