// "A single ratio against a limit" per the dataviz skill's form table --
// same-ramp track, always labeled. Severity already lives on the insight's
// Badge (critical/warning) -- the meter itself stays in the brand hue
// rather than re-encoding severity as a second, redundant color channel.
export function Meter({
  label,
  value,
  limit,
  valueLabel,
}: {
  label: string;
  value: number;
  limit: number;
  valueLabel: string;
}) {
  const fraction = limit > 0 ? Math.max(0, Math.min(1, value / limit)) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums text-foreground">{valueLabel}</span>
      </div>
      <div className="h-3 w-full rounded-sm bg-chart-track">
        <div className="h-full rounded-r bg-brand" style={{ width: `${fraction * 100}%` }} />
      </div>
    </div>
  );
}
