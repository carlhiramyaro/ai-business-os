"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  AdjustmentReason,
  ExpenseListItem,
  GetToken,
  Product,
  ProductUpdateInput,
  SaleListItem,
  createStockAdjustment,
  declareProductUnit,
  getSuggestedSku,
  listExpenses,
  listProducts,
  listSales,
  updateProduct,
} from "@/lib/api";
import { BusinessPicker } from "@/components/BusinessPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";

type Tab = "inventory" | "sales" | "expenses";

const TABS: { value: Tab; label: string }[] = [
  { value: "inventory", label: "Inventory" },
  { value: "sales", label: "Sales" },
  { value: "expenses", label: "Expenses" },
];

function money(value: string | null) {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : value;
}

export default function InventoryPage() {
  const { getToken, loading } = useAuth();
  const [businessId, setBusinessId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("inventory");

  if (loading) return null;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-16">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Inventory</h1>
        <p className="text-sm text-muted">
          Current stock, and a plain list of your sales and expenses — no need to ask chat.
        </p>
      </div>

      <Card>
        <label className="mb-2 block text-sm font-medium text-foreground">Business</label>
        <BusinessPicker getToken={getToken} selectedBusinessId={businessId} onSelect={setBusinessId} />
      </Card>

      {businessId && (
        <>
          <div className="flex gap-1 rounded-lg border border-border bg-surface p-1">
            {TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setTab(t.value)}
                className={`min-h-11 flex-1 rounded-md py-2.5 text-sm font-medium transition-colors ${
                  tab === t.value ? "bg-brand text-brand-foreground" : "text-muted hover:text-foreground"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "inventory" && <InventoryTab getToken={getToken} businessId={businessId} />}
          {tab === "sales" && <SalesTab getToken={getToken} businessId={businessId} />}
          {tab === "expenses" && <ExpensesTab getToken={getToken} businessId={businessId} />}
        </>
      )}
    </div>
  );
}

function InventoryTab({ getToken, businessId }: { getToken: GetToken; businessId: string }) {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [openPanel, setOpenPanel] = useState<{ productId: string; mode: "adjust" | "edit" } | null>(null);
  // Adjust state during render rather than an effect (same pattern
  // NavBar.tsx uses for pathname changes) -- avoids the cascading-render
  // an effect that calls setState synchronously would trigger.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  function refresh() {
    setError(null);
    setProducts(null);
    listProducts(getToken, businessId)
      .then(setProducts)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load inventory"));
  }

  if (loadedFor !== businessId) {
    setLoadedFor(businessId);
    refresh();
  }

  const filtered = (products ?? []).filter((p) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return p.name.toLowerCase().includes(q) || (p.sku ?? "").toLowerCase().includes(q);
  });

  function handleAdjusted(productId: string, currentStock: number) {
    setProducts((prev) =>
      prev?.map((p) => (p.id === productId ? { ...p, quantity: currentStock, lowStock: p.reorderLevel !== null && currentStock <= p.reorderLevel } : p)) ??
        null
    );
    setOpenPanel(null);
  }

  function handleEdited(updated: Product) {
    setProducts((prev) => prev?.map((p) => (p.id === updated.id ? updated : p)) ?? null);
    setOpenPanel(null);
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <p className="text-sm text-danger-fg">{error}</p>}

      {products && products.length > 0 && (
        <Input placeholder="Search by name or SKU" value={search} onChange={(e) => setSearch(e.target.value)} />
      )}

      {products === null && !error && <p className="text-sm text-muted">Loading…</p>}

      {products && products.length === 0 && (
        <Card>
          <p className="text-sm text-muted">
            No products yet — they show up here once you record a sale or inventory entry (web, WhatsApp, or a CSV
            upload).
          </p>
        </Card>
      )}

      {products && products.length > 0 && filtered.length === 0 && (
        <Card>
          <p className="text-sm text-muted">No products match &ldquo;{search}&rdquo;.</p>
        </Card>
      )}

      {filtered.map((product) => (
        <Card key={product.id} className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium text-foreground">{product.name}</p>
                {product.sku && <Badge tone="neutral">{product.sku}</Badge>}
                {product.lowStock && <Badge tone="warning">Low stock</Badge>}
              </div>
              <p className="text-sm text-muted">
                {product.quantity} {product.baseUnit}
                {product.reorderLevel !== null && ` · reorder at ${product.reorderLevel}`}
                {product.costPrice !== null && ` · cost ${money(product.costPrice)}`}
                {product.sellingPrice !== null && ` · sells ${money(product.sellingPrice)}`}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                variant="secondary"
                onClick={() =>
                  setOpenPanel(
                    openPanel?.productId === product.id && openPanel.mode === "edit"
                      ? null
                      : { productId: product.id, mode: "edit" }
                  )
                }
              >
                {openPanel?.productId === product.id && openPanel.mode === "edit" ? "Cancel" : "Edit"}
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  setOpenPanel(
                    openPanel?.productId === product.id && openPanel.mode === "adjust"
                      ? null
                      : { productId: product.id, mode: "adjust" }
                  )
                }
              >
                {openPanel?.productId === product.id && openPanel.mode === "adjust" ? "Cancel" : "Adjust"}
              </Button>
            </div>
          </div>

          {openPanel?.productId === product.id && openPanel.mode === "edit" && (
            <EditForm
              getToken={getToken}
              businessId={businessId}
              product={product}
              onEdited={handleEdited}
            />
          )}

          {openPanel?.productId === product.id && openPanel.mode === "adjust" && (
            <AdjustForm
              getToken={getToken}
              businessId={businessId}
              product={product}
              onAdjusted={(currentStock) => handleAdjusted(product.id, currentStock)}
            />
          )}
        </Card>
      ))}
    </div>
  );
}

function EditForm({
  getToken,
  businessId,
  product,
  onEdited,
}: {
  getToken: GetToken;
  businessId: string;
  product: Product;
  onEdited: (updated: Product) => void;
}) {
  const [sku, setSku] = useState(product.sku ?? "");
  const [category, setCategory] = useState(product.category ?? "");
  const [baseUnit, setBaseUnit] = useState(product.baseUnit);
  const [reorderLevel, setReorderLevel] = useState(product.reorderLevel?.toString() ?? "");
  const [costPrice, setCostPrice] = useState(product.costPrice ?? "");
  const [sellingPrice, setSellingPrice] = useState(product.sellingPrice ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [suggesting, setSuggesting] = useState(false);

  async function handleSuggestSku() {
    setError(null);
    setSuggesting(true);
    try {
      const { sku: suggested } = await getSuggestedSku(getToken, businessId, product.id);
      setSku(suggested);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not suggest a SKU");
    } finally {
      setSuggesting(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const update: ProductUpdateInput = {
        sku: sku || undefined,
        category: category || undefined,
        baseUnit: baseUnit || undefined,
        reorderLevel: reorderLevel === "" ? undefined : Number(reorderLevel),
        costPrice: costPrice || undefined,
        sellingPrice: sellingPrice || undefined,
      };
      const updated = await updateProduct(getToken, businessId, product.id, update);
      onEdited(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save changes");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 border-t border-border pt-3">
      {error && <p className="text-sm text-danger-fg">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="SKU">
          <div className="flex gap-2">
            <Input
              placeholder="e.g. RICE-5KG"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              className="min-w-0 flex-1"
            />
            {sku.trim() === "" && (
              <Button type="button" variant="secondary" onClick={handleSuggestSku} disabled={suggesting}>
                {suggesting ? "…" : "Suggest"}
              </Button>
            )}
          </div>
        </Field>
        <Field label="Category">
          <Input placeholder="e.g. Grains" value={category} onChange={(e) => setCategory(e.target.value)} />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Unit">
          <Input placeholder="e.g. piece" value={baseUnit} onChange={(e) => setBaseUnit(e.target.value)} required />
        </Field>
        <Field label="Reorder level">
          <Input
            type="number"
            inputMode="numeric"
            min="0"
            value={reorderLevel}
            onChange={(e) => setReorderLevel(e.target.value)}
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Cost price">
          <Input
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={costPrice}
            onChange={(e) => setCostPrice(e.target.value)}
          />
        </Field>
        <Field label="Selling price">
          <Input
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={sellingPrice}
            onChange={(e) => setSellingPrice(e.target.value)}
          />
        </Field>
      </div>
      <Button type="submit" disabled={submitting}>
        {submitting ? "Saving…" : "Save details"}
      </Button>
    </form>
  );
}

const REASON_OPTIONS: { value: AdjustmentReason; label: string }[] = [
  { value: "restock", label: "Restock (received more)" },
  { value: "recount", label: "Recount (set the actual count)" },
  { value: "loss", label: "Loss" },
  { value: "damage", label: "Damage" },
];

function AdjustForm({
  getToken,
  businessId,
  product,
  onAdjusted,
}: {
  getToken: GetToken;
  businessId: string;
  product: Product;
  onAdjusted: (currentStock: number) => void;
}) {
  const [reason, setReason] = useState<AdjustmentReason>("restock");
  const [quantity, setQuantity] = useState("");
  const [unitName, setUnitName] = useState("");
  const [conversionToBase, setConversionToBase] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const usingOtherUnit = unitName.trim().length > 0;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!quantity) return;
    setError(null);
    setSubmitting(true);
    try {
      if (usingOtherUnit) {
        if (!conversionToBase) {
          setError(`How many ${product.baseUnit} is one "${unitName}"?`);
          setSubmitting(false);
          return;
        }
        await declareProductUnit(getToken, businessId, product.id, {
          unitName: unitName.trim(),
          conversionToBase,
        });
      }
      const result = await createStockAdjustment(getToken, businessId, product.id, {
        reason,
        quantity: Number(quantity),
        unitName: usingOtherUnit ? unitName.trim() : undefined,
        note: note || undefined,
      });
      onAdjusted(result.currentStock);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save adjustment");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 border-t border-border pt-3">
      {error && <p className="text-sm text-danger-fg">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Reason">
          <Select value={reason} onChange={(e) => setReason(e.target.value as AdjustmentReason)}>
            {REASON_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={reason === "recount" ? "New count" : "Quantity"}>
          <Input
            type="number"
            inputMode="numeric"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label={`Unit (optional, default ${product.baseUnit})`}>
          <Input placeholder="e.g. carton" value={unitName} onChange={(e) => setUnitName(e.target.value)} />
        </Field>
        {usingOtherUnit && (
          <Field label={`= how many ${product.baseUnit}?`}>
            <Input
              type="number"
              inputMode="decimal"
              min="0"
              value={conversionToBase}
              onChange={(e) => setConversionToBase(e.target.value)}
              required
            />
          </Field>
        )}
      </div>
      <Field label="Note (optional)">
        <Input placeholder="e.g. supplier delivery" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Button type="submit" disabled={submitting || !quantity}>
        {submitting ? "Saving…" : "Save adjustment"}
      </Button>
    </form>
  );
}

function SalesTab({ getToken, businessId }: { getToken: GetToken; businessId: string }) {
  const [sales, setSales] = useState<SaleListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  if (loadedFor !== businessId) {
    setLoadedFor(businessId);
    setError(null);
    listSales(getToken, businessId)
      .then(setSales)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load sales"));
  }

  if (error) return <p className="text-sm text-danger-fg">{error}</p>;
  if (sales === null) return <p className="text-sm text-muted">Loading…</p>;
  if (sales.length === 0)
    return (
      <Card>
        <p className="text-sm text-muted">No sales recorded yet.</p>
      </Card>
    );

  return (
    <div className="flex flex-col gap-3">
      {sales.map((sale) => (
        <Card key={sale.id} className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <p className="font-medium text-foreground">{sale.productName ?? "—"}</p>
            <p className="text-sm text-muted">
              {sale.saleDate ?? "no date"}
              {sale.quantity !== null && ` · qty ${sale.quantity}`}
              {sale.customerName && ` · ${sale.customerName}`}
              {sale.paymentMethod && ` · ${sale.paymentMethod}`}
            </p>
          </div>
          <p className="shrink-0 font-medium text-foreground">{money(sale.totalAmount)}</p>
        </Card>
      ))}
    </div>
  );
}

function ExpensesTab({ getToken, businessId }: { getToken: GetToken; businessId: string }) {
  const [expenses, setExpenses] = useState<ExpenseListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  if (loadedFor !== businessId) {
    setLoadedFor(businessId);
    setError(null);
    listExpenses(getToken, businessId)
      .then(setExpenses)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load expenses"));
  }

  if (error) return <p className="text-sm text-danger-fg">{error}</p>;
  if (expenses === null) return <p className="text-sm text-muted">Loading…</p>;
  if (expenses.length === 0)
    return (
      <Card>
        <p className="text-sm text-muted">No expenses recorded yet.</p>
      </Card>
    );

  return (
    <div className="flex flex-col gap-3">
      {expenses.map((expense) => (
        <Card key={expense.id} className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <p className="font-medium text-foreground">{expense.category ?? "—"}</p>
            <p className="text-sm text-muted">
              {expense.expenseDate ?? "no date"}
              {expense.vendor && ` · ${expense.vendor}`}
              {expense.description && ` · ${expense.description}`}
            </p>
          </div>
          <p className="shrink-0 font-medium text-foreground">{money(expense.amount)}</p>
        </Card>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-foreground">{label}</span>
      {children}
    </label>
  );
}
