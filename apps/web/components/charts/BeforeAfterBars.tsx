import { formatPercent } from "./format";

type DeltaTone = "success" | "warning" | "danger";

const DELTA_TONE_CLASSES: Record<DeltaTone, string> = {
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
  danger: "bg-danger-bg text-danger-fg",
};

function Bar({
  label,
  formattedValue,
  fraction,
  colorVar,
}: {
  label: string;
  formattedValue: string;
  fraction: number;
  colorVar: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="min-w-0 truncate text-muted">{label}</span>
        <span className="shrink-0 font-medium tabular-nums text-foreground">{formattedValue}</span>
      </div>
      <div className="h-3 w-full rounded-sm bg-chart-track">
        <div
          className="h-full rounded-r"
          style={{ width: `${Math.max(0, Math.min(1, fraction)) * 100}%`, backgroundColor: colorVar }}
        />
      </div>
    </div>
  );
}

// "Before -> after per item" per the dataviz skill's form table: one hue,
// two shades, direct labels -- not a categorical comparison, so no legend.
export function BeforeAfterBars({
  priorLabel,
  priorValue,
  recentLabel,
  recentValue,
  pctChange,
  deltaTone,
  format,
}: {
  priorLabel: string;
  priorValue: number;
  recentLabel: string;
  recentValue: number;
  pctChange: number;
  deltaTone: DeltaTone;
  format: (value: number) => string;
}) {
  const max = Math.max(priorValue, recentValue, 1);
  return (
    <div className="flex flex-col gap-2">
      <Bar label={priorLabel} formattedValue={format(priorValue)} fraction={priorValue / max} colorVar="var(--chart-2)" />
      <Bar label={recentLabel} formattedValue={format(recentValue)} fraction={recentValue / max} colorVar="var(--chart-3)" />
      <span className={`self-start rounded-full px-2 py-0.5 text-xs font-medium ${DELTA_TONE_CLASSES[deltaTone]}`}>
        {formatPercent(pctChange)}
      </span>
    </div>
  );
}
