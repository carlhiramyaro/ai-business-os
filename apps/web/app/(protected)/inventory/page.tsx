"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  AdjustmentReason,
  ExpenseListItem,
  GetToken,
  PackRelationship,
  Product,
  ProductUpdateInput,
  SaleListItem,
  createRepack,
  createStockAdjustment,
  declarePackRelationship,
  getPackRelationship,
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

// Quantities arrive as exact Decimal strings (possibly with trailing
// zeros, e.g. "5.0000000000") -- trims those for display without forcing
// a fixed number of decimal places the way money() does, since "5" should
// read as "5", not "5.00".
function qty(value: string) {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
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
  const [openPanel, setOpenPanel] = useState<{ productId: string; mode: "adjust" | "edit" | "pack" } | null>(null);
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

  // Adjust/Edit/Pack all just trigger a full refetch on success rather
  // than hand-patching state -- a repack changes TWO products' stock at
  // once, which a local patch can't express cleanly, so every panel uses
  // the same simple "refresh and close" completion.
  function handleChanged() {
    refresh();
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

      {filtered.map((product) => {
        const panelMode = openPanel?.productId === product.id ? openPanel.mode : null;
        function togglePanel(mode: "adjust" | "edit" | "pack") {
          setOpenPanel(panelMode === mode ? null : { productId: product.id, mode });
        }

        return (
          <Card key={product.id} className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-foreground">{product.name}</p>
                  {product.sku && <Badge tone="neutral">{product.sku}</Badge>}
                  {product.lowStock && <Badge tone="warning">Low stock</Badge>}
                </div>
                <p className="text-sm text-muted">
                  {qty(product.quantity)} {product.baseUnit}
                  {product.reorderLevel !== null && ` · reorder at ${qty(product.reorderLevel)}`}
                  {product.costPrice !== null && ` · cost ${money(product.costPrice)}`}
                  {product.sellingPrice !== null && ` · sells ${money(product.sellingPrice)}`}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap justify-end gap-2">
                <Button variant="secondary" onClick={() => togglePanel("edit")}>
                  {panelMode === "edit" ? "Cancel" : "Edit"}
                </Button>
                <Button variant="secondary" onClick={() => togglePanel("pack")}>
                  {panelMode === "pack" ? "Cancel" : "Pack"}
                </Button>
                <Button variant="secondary" onClick={() => togglePanel("adjust")}>
                  {panelMode === "adjust" ? "Cancel" : "Adjust"}
                </Button>
              </div>
            </div>

            {panelMode === "edit" && (
              <EditForm getToken={getToken} businessId={businessId} product={product} onChanged={handleChanged} />
            )}

            {panelMode === "pack" && (
              <PackForm
                getToken={getToken}
                businessId={businessId}
                products={products ?? []}
                product={product}
                onChanged={handleChanged}
              />
            )}

            {panelMode === "adjust" && (
              <AdjustForm getToken={getToken} businessId={businessId} product={product} onChanged={handleChanged} />
            )}
          </Card>
        );
      })}
    </div>
  );
}

function EditForm({
  getToken,
  businessId,
  product,
  onChanged,
}: {
  getToken: GetToken;
  businessId: string;
  product: Product;
  onChanged: () => void;
}) {
  const [sku, setSku] = useState(product.sku ?? "");
  const [category, setCategory] = useState(product.category ?? "");
  const [baseUnit, setBaseUnit] = useState(product.baseUnit);
  const [reorderLevel, setReorderLevel] = useState(product.reorderLevel ?? "");
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
        reorderLevel: reorderLevel === "" ? undefined : reorderLevel,
        costPrice: costPrice || undefined,
        sellingPrice: sellingPrice || undefined,
      };
      await updateProduct(getToken, businessId, product.id, update);
      onChanged();
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
            inputMode="decimal"
            step="any"
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
  onChanged,
}: {
  getToken: GetToken;
  businessId: string;
  product: Product;
  onChanged: () => void;
}) {
  const [reason, setReason] = useState<AdjustmentReason>("restock");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!quantity) return;
    setError(null);
    setSubmitting(true);
    try {
      await createStockAdjustment(getToken, businessId, product.id, {
        reason,
        quantity,
        note: note || undefined,
      });
      onChanged();
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
        <Field label={reason === "recount" ? `New count (${product.baseUnit})` : `Quantity (${product.baseUnit})`}>
          <Input
            type="number"
            inputMode="decimal"
            step="any"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </Field>
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

// Pack relationships (docs/decisions.md [2026-09-14]) -- "1 Coke Case = 24
// Coke Can" as an explicit link between two independent products, plus the
// "break"/"assemble" repack action that converts between them. Replaces an
// earlier per-transaction unit conversion that turned out to be a
// confusing setup flow disconnected from the sale/restock it served.
function PackForm({
  getToken,
  businessId,
  products,
  product,
  onChanged,
}: {
  getToken: GetToken;
  businessId: string;
  products: Product[];
  product: Product;
  onChanged: () => void;
}) {
  // undefined = still loading; null = loaded, no relationship declared yet.
  const [relationship, setRelationship] = useState<PackRelationship | null | undefined>(undefined);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (loadedFor !== product.id) {
    setLoadedFor(product.id);
    getPackRelationship(getToken, businessId, product.id)
      .then(setRelationship)
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Could not load pack info");
        setRelationship(null);
      });
  }

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3">
      {error && <p className="text-sm text-danger-fg">{error}</p>}
      {relationship === undefined ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : relationship ? (
        <RepackForm
          getToken={getToken}
          businessId={businessId}
          product={product}
          relationship={relationship}
          onChanged={onChanged}
        />
      ) : (
        <DeclarePackForm
          getToken={getToken}
          businessId={businessId}
          products={products}
          product={product}
          onDeclared={setRelationship}
        />
      )}
    </div>
  );
}

function DeclarePackForm({
  getToken,
  businessId,
  products,
  product,
  onDeclared,
}: {
  getToken: GetToken;
  businessId: string;
  products: Product[];
  product: Product;
  onDeclared: (relationship: PackRelationship) => void;
}) {
  const otherProducts = products.filter((p) => p.id !== product.id);
  const [unitProductId, setUnitProductId] = useState(otherProducts[0]?.id ?? "");
  const [unitsPerPack, setUnitsPerPack] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!unitProductId || !unitsPerPack) return;
    setError(null);
    setSubmitting(true);
    try {
      const relationship = await declarePackRelationship(getToken, businessId, product.id, {
        unitProductId,
        unitsPerPack,
      });
      onDeclared(relationship);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not link products");
    } finally {
      setSubmitting(false);
    }
  }

  if (otherProducts.length === 0) {
    return <p className="text-sm text-muted">Add another product first, then come back to link them.</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        Is <span className="font-medium text-foreground">{product.name}</span> a sealed pack of another product —
        e.g. a case of cans? Link them once, then use &ldquo;Break a case&rdquo; whenever you open one, instead of
        converting units on every sale.
      </p>
      {error && <p className="text-sm text-danger-fg">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Contains">
          <Select value={unitProductId} onChange={(e) => setUnitProductId(e.target.value)}>
            {otherProducts.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={`How many per ${product.name}?`}>
          <Input
            type="number"
            inputMode="decimal"
            step="any"
            min="0"
            value={unitsPerPack}
            onChange={(e) => setUnitsPerPack(e.target.value)}
            required
          />
        </Field>
      </div>
      <Button type="submit" disabled={submitting}>
        {submitting ? "Linking…" : "Link products"}
      </Button>
    </form>
  );
}

function RepackForm({
  getToken,
  businessId,
  product,
  relationship,
  onChanged,
}: {
  getToken: GetToken;
  businessId: string;
  product: Product;
  relationship: PackRelationship;
  onChanged: () => void;
}) {
  const [direction, setDirection] = useState<"break" | "assemble">("break");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!quantity) return;
    setError(null);
    setSubmitting(true);
    try {
      await createRepack(getToken, businessId, product.id, { quantity, direction, note: note || undefined });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        Linked: 1 {product.name} = {qty(relationship.unitsPerPack)} {relationship.unitProductName}
      </p>
      {error && <p className="text-sm text-danger-fg">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Action">
          <Select value={direction} onChange={(e) => setDirection(e.target.value as "break" | "assemble")}>
            <option value="break">Break {product.name} → {relationship.unitProductName}</option>
            <option value="assemble">Assemble {relationship.unitProductName} → {product.name}</option>
          </Select>
        </Field>
        <Field label={direction === "break" ? `How many ${product.name}?` : `How many ${product.name} to make?`}>
          <Input
            type="number"
            inputMode="decimal"
            step="any"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </Field>
      </div>
      <Field label="Note (optional)">
        <Input value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Button type="submit" disabled={submitting || !quantity}>
        {submitting ? "Saving…" : "Save"}
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
