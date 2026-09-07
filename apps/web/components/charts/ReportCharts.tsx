import { ReportMetrics } from "@/lib/api";
import { BarChart } from "./BarChart";
import { LineChart } from "./LineChart";
import { StatTile } from "./StatTile";
import { formatCurrency, formatPercent } from "./format";

export function ReportCharts({ metrics, currency }: { metrics: ReportMetrics; currency: string }) {
  const format = (value: number) => formatCurrency(value, currency);
  const { finance, marketing } = metrics;
  const expenseItems = Object.entries(finance.expenseBreakdown).map(([label, value]) => ({ label, value }));
  const topProductItems = marketing.topProducts.map((p) => ({ label: p.productName, value: p.totalRevenue }));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-sm font-semibold text-foreground">At a glance</h2>
        <div className="mt-2 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile label="Revenue" value={format(finance.totalRevenue)} />
          <StatTile label="Expenses" value={format(finance.totalExpenses)} />
          <StatTile
            label="Profit"
            value={format(finance.profit)}
            delta={finance.profit >= 0 ? undefined : "Loss"}
            deltaTone={finance.profit >= 0 ? undefined : "danger"}
          />
          <StatTile label="Margin" value={finance.profitMargin != null ? formatPercent(finance.profitMargin) : "—"} />
        </div>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-foreground">Daily revenue</h2>
        <div className="mt-2">
          <LineChart points={metrics.dailyRevenue} format={format} />
        </div>
      </div>

      {expenseItems.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-foreground">Expenses by category</h2>
          <div className="mt-2">
            <BarChart items={expenseItems} format={format} />
          </div>
        </div>
      )}

      {topProductItems.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-foreground">Top products</h2>
          <div className="mt-2">
            <BarChart items={topProductItems} format={format} />
          </div>
        </div>
      )}
    </div>
  );
}
