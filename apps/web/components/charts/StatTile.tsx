type DeltaTone = "success" | "warning" | "danger";

const DELTA_TEXT_CLASSES: Record<DeltaTone, string> = {
  success: "text-success-fg",
  warning: "text-warning-fg",
  danger: "text-danger-fg",
};

// "A single current value" per the dataviz skill's form table -- not a
// one-bar bar chart. Proportional figures; tabular-nums only where values
// must align in a stacked row of tiles.
export function StatTile({
  label,
  value,
  delta,
  deltaTone,
}: {
  label: string;
  value: string;
  delta?: string;
  deltaTone?: DeltaTone;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted">{label}</span>
      <span className="text-lg font-semibold tabular-nums text-foreground">{value}</span>
      {delta && (
        <span className={`text-xs font-medium ${deltaTone ? DELTA_TEXT_CLASSES[deltaTone] : "text-muted"}`}>
          {delta}
        </span>
      )}
    </div>
  );
}
