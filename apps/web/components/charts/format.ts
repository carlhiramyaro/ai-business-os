// Business currency is a required ISO 4217 code (see Business.currency in
// lib/api.ts) -- never hardcode "$", a GHS business must render GHS.
export function formatCurrency(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${currency} ${Math.round(value).toLocaleString()}`;
  }
}

// value is a fraction (0.22 -> "+22%"), matching signals.py's pctChange.
export function formatPercent(value: number): string {
  const pct = Math.round(value * 100);
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct}%`;
}
