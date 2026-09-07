import {
  ExpenseSpikeMetrics,
  Insight,
  InactiveCustomersMetrics,
  RevenueTrendMetrics,
  StockDepletionMetrics,
} from "@/lib/api";
import { BeforeAfterBars } from "./BeforeAfterBars";
import { Meter } from "./Meter";
import { StatTile } from "./StatTile";
import { formatCurrency } from "./format";

const STOCK_DEPLETION_HORIZON_DAYS = 7; // matches forecasting.py's DEFAULT_HORIZON_DAYS

// insights.metrics is dict[str, Any] on the backend (schemas/insights.py) --
// not schema-validated, so these guards are the actual safety net, not a
// formality. A shape that doesn't match renders no chart, which is correct
// for an old row written before a metrics shape changed.
function isRevenueTrendMetrics(m: Record<string, unknown>): m is Record<string, unknown> & RevenueTrendMetrics {
  return typeof m.recentWeekRevenue === "number" && typeof m.priorWeekRevenue === "number" && typeof m.pctChange === "number";
}

function isExpenseSpikeMetrics(m: Record<string, unknown>): m is Record<string, unknown> & ExpenseSpikeMetrics {
  return typeof m.recentAmount === "number" && typeof m.baselineAmount === "number" && typeof m.pctChange === "number";
}

function isStockDepletionMetrics(m: Record<string, unknown>): m is Record<string, unknown> & StockDepletionMetrics {
  return (
    typeof m.quantity === "number" &&
    typeof m.dailyVelocity === "number" &&
    (m.daysToStockout === null || typeof m.daysToStockout === "number")
  );
}

function isInactiveCustomersMetrics(m: Record<string, unknown>): m is Record<string, unknown> & InactiveCustomersMetrics {
  return typeof m.count === "number" && typeof m.inactiveSinceDays === "number";
}

// Renders nothing on an unrecognized insightType or a malformed/missing
// metrics blob -- per the plan, a missing chart is correct behavior here,
// not an error.
export function InsightVisual({ insight, currency }: { insight: Insight; currency: string }) {
  const format = (value: number) => formatCurrency(value, currency);
  const m = insight.metrics;

  switch (insight.insightType) {
    case "revenue_trend": {
      if (!isRevenueTrendMetrics(m)) return null;
      return (
        <BeforeAfterBars
          priorLabel="Prior week"
          priorValue={m.priorWeekRevenue}
          recentLabel="Recent week"
          recentValue={m.recentWeekRevenue}
          pctChange={m.pctChange}
          deltaTone={m.pctChange >= 0 ? "success" : "danger"}
          format={format}
        />
      );
    }
    case "expense_spike": {
      if (!isExpenseSpikeMetrics(m)) return null;
      return (
        <BeforeAfterBars
          priorLabel="Baseline"
          priorValue={m.baselineAmount}
          recentLabel="Recent"
          recentValue={m.recentAmount}
          pctChange={m.pctChange}
          deltaTone="danger"
          format={format}
        />
      );
    }
    case "stock_depletion": {
      if (!isStockDepletionMetrics(m)) return null;
      return (
        <div className="flex flex-col gap-3">
          <Meter
            label="Days to stockout"
            value={m.daysToStockout ?? STOCK_DEPLETION_HORIZON_DAYS}
            limit={STOCK_DEPLETION_HORIZON_DAYS}
            valueLabel={m.daysToStockout != null ? `${m.daysToStockout}d` : "—"}
          />
          <div className="flex gap-4">
            <StatTile label="Quantity left" value={String(m.quantity)} />
            <StatTile label="Units/day" value={m.dailyVelocity.toFixed(1)} />
          </div>
        </div>
      );
    }
    case "inactive_customers": {
      if (!isInactiveCustomersMetrics(m)) return null;
      return (
        <div className="flex gap-4">
          <StatTile label="Customers" value={String(m.count)} />
          <StatTile label="Inactive for" value={`${m.inactiveSinceDays}d+`} />
        </div>
      );
    }
    default:
      return null;
  }
}
