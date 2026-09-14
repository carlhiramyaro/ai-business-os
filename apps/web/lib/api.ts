// Hand-written types mirroring docs/endpoints.md's auth response shapes.
// See docs/learning-guide.md Part 3.5 — these will drift from the backend
// unless kept in sync manually, or later generated from FastAPI's OpenAPI
// schema once there are enough endpoints to make that worthwhile.

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export interface AuthUser {
  id: string;
  fullName: string;
  email: string;
  createdAt: string;
}

interface ApiError {
  detail: string;
}

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) {
    throw new Error((body as ApiError).detail ?? "Request failed");
  }
  return body as T;
}

export function getCurrentUser(accessToken: string) {
  return fetch(`${API_URL}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  }).then((response) => parseJsonOrThrow<AuthUser>(response));
}

// Clerk session tokens are short-lived by design (see Clerk's docs on
// session token lifetime) -- callers pass the SDK's getToken() rather than
// a cached string, so every request fetches a fresh one instead of risking
// a stale token a few requests into a long-lived page.
export type GetToken = () => Promise<string | null>;

async function authHeaders(getToken: GetToken) {
  return { Authorization: `Bearer ${await getToken()}` };
}

export interface Business {
  id: string;
  ownerId: string;
  businessName: string;
  industry: string | null;
  currency: string | null;
  country: string | null;
  timezone: string | null;
  createdAt: string;
  updatedAt: string;
}

export async function createBusiness(getToken: GetToken, businessName: string) {
  return fetch(`${API_URL}/api/v1/businesses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify({ businessName }),
  }).then((response) => parseJsonOrThrow<Business>(response));
}

export async function listBusinesses(getToken: GetToken) {
  return fetch(`${API_URL}/api/v1/businesses/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<Business[]>(response));
}

export async function getBusiness(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<Business>(response));
}

export interface UploadCreateResponse {
  uploadSessionId: string;
  status: string;
}

export async function createUpload(
  getToken: GetToken,
  businessId: string,
  files: { sales?: File; inventory?: File; expenses?: File }
) {
  const formData = new FormData();
  if (files.sales) formData.append("sales", files.sales);
  if (files.inventory) formData.append("inventory", files.inventory);
  if (files.expenses) formData.append("expenses", files.expenses);

  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: formData,
  }).then((response) => parseJsonOrThrow<UploadCreateResponse>(response));
}

export interface UploadSessionSummary {
  id: string;
  status: string;
  uploadedAt: string;
}

export async function listUploads(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<UploadSessionSummary[]>(response));
}

export type UploadStatusValue = "PROCESSING" | "NEEDS_REVIEW" | "COMPLETED" | "FAILED";

export interface UploadStatus {
  status: UploadStatusValue;
  progress: number;
  pendingReview: string[] | null;
  // True when ingestion detected rows that look like a repeat of data
  // already in the business's tables (v0.3 dedup safeguard, warn-only --
  // rows are still ingested, never dropped). See app/ingestion.py.
  duplicateWarning: boolean;
}

export async function getUploadStatus(getToken: GetToken, businessId: string, uploadSessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<UploadStatus>(response));
}

export interface ColumnMapping {
  id: string;
  datasetType: string;
  sourceColumnName: string;
  targetField: string;
  confidenceScore: number;
  mappingMethod: string;
  sampleValues: string[] | null;
}

export async function getColumnMappings(getToken: GetToken, businessId: string, uploadSessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}/column-mappings`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ColumnMapping[]>(response));
}

export async function updateColumnMapping(
  getToken: GetToken,
  businessId: string,
  uploadSessionId: string,
  mappingId: string,
  targetField: string
) {
  return fetch(
    `${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}/column-mappings/${mappingId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
      body: JSON.stringify({ targetField }),
    }
  ).then((response) => parseJsonOrThrow<ColumnMapping>(response));
}

export async function confirmColumnMappings(getToken: GetToken, businessId: string, uploadSessionId: string) {
  return fetch(
    `${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}/column-mappings/confirm`,
    { method: "POST", headers: await authHeaders(getToken) }
  ).then((response) => parseJsonOrThrow<{ status: string }>(response));
}

// Mirrors app/column_mapping.py's CANONICAL_FIELDS -- keep in sync manually
// (same drift risk noted at the top of this file).
export const CANONICAL_FIELDS: Record<string, string[]> = {
  sales: [
    "saleDate",
    "productName",
    "category",
    "quantity",
    "unitPrice",
    "discount",
    "totalAmount",
    "customerName",
    "customerPhone",
    "paymentMethod",
  ],
  inventory: ["productName", "category", "quantity", "reorderLevel", "supplier", "costPrice", "sellingPrice"],
  expenses: ["expenseDate", "category", "vendor", "amount", "description"],
};

// Mirrors app/tasks.py's MAPPING_CONFIDENCE_THRESHOLD default. Not yet
// exposed by the API, so this is a hardcoded second copy -- exactly the
// drift risk docs/decisions.md's 2026-07-12 entry #5 warned about. Should
// become a value the frontend reads from the backend instead.
export const MAPPING_CONFIDENCE_THRESHOLD = 0.8;

// Mirrors app/column_mapping.py's IGNORE_FIELD sentinel -- same drift risk
// as above. Lets a user mark a source column as "not needed" instead of
// being forced to pick a canonical field for it.
export const IGNORE_FIELD = "ignore";

export type ReportStatus = "PENDING" | "COMPLETED" | "FAILED";

export interface ReportSummary {
  id: string;
  createdAt: string;
  periodStart: string;
  periodEnd: string;
  status: ReportStatus;
  businessHealth: string;
}

// Composed and persisted at generation time by app/report_generation.py --
// a fixed, internally-controlled shape (unlike Insight.metrics, which
// grows a new variant per detector added to signals.py), so it's typed
// directly rather than behind runtime guards.
export interface ReportFinanceMetrics {
  totalRevenue: number;
  totalExpenses: number;
  profit: number;
  profitMargin: number | null;
  expenseBreakdown: Record<string, number>;
}

export interface ReportInventoryMetrics {
  lowStockItems: { productName: string; quantity: number; reorderLevel: number }[];
  totalInventoryValue: number;
  totalInventoryItems: number;
}

export interface ReportMarketingMetrics {
  topProducts: { productName: string; totalRevenue: number }[];
  paymentMethodBreakdown: Record<string, number>;
}

export interface ReportOperationsMetrics {
  totalOrders: number;
  averageDiscount: number;
  dateRangeStart: string | null;
  dateRangeEnd: string | null;
}

export interface ReportDailyRevenuePoint {
  date: string;
  revenue: number;
}

export interface ReportMetrics {
  finance: ReportFinanceMetrics;
  inventory: ReportInventoryMetrics;
  marketing: ReportMarketingMetrics;
  operations: ReportOperationsMetrics;
  dailyRevenue: ReportDailyRevenuePoint[];
}

export interface ReportDetail {
  periodStart: string;
  periodEnd: string;
  status: ReportStatus;
  summary: string | null;
  risks: string[];
  opportunities: string[];
  forecast: string | null;
  actionPlan: string[];
  // null for reports generated before this field existed -- no backfill.
  metrics: ReportMetrics | null;
}

export interface ReportGenerateResponse {
  reportId: string;
  status: ReportStatus;
}

export async function listReports(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ReportSummary[]>(response));
}

export async function generateReport(getToken: GetToken, businessId: string, periodStart: string, periodEnd: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify({ periodStart, periodEnd }),
  }).then((response) => parseJsonOrThrow<ReportGenerateResponse>(response));
}

export async function getReport(getToken: GetToken, businessId: string, reportId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/${reportId}`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ReportDetail>(response));
}

export async function deleteReport(getToken: GetToken, businessId: string, reportId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/${reportId}`, {
    method: "DELETE",
    headers: await authHeaders(getToken),
  });
}

export interface ConversationCreateResponse {
  conversationId: string;
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ChatToolCall[] | null;
  createdAt: string;
}

export interface ConversationHistory {
  conversationId: string;
  messages: MessageItem[];
}

export async function createConversation(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/chat/`, {
    method: "POST",
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ConversationCreateResponse>(response));
}

export interface ChatToolCall {
  tool: string;
  arguments: Record<string, unknown>;
}

export async function sendChatMessage(getToken: GetToken, businessId: string, conversationId: string, message: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/chat/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify({ message }),
  }).then((response) => parseJsonOrThrow<{ answer: string; toolCalls: ChatToolCall[] }>(response));
}

export async function getConversation(getToken: GetToken, businessId: string, conversationId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/chat/${conversationId}`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ConversationHistory>(response));
}

// Quick manual entry (v0.3) -- one-row batches through the same ingest
// boundary the CSV pipeline uses. See app/ingestion.py, docs/decisions.md
// [2026-07-24].

export interface EntryCreateResponse {
  id: string;
  duplicateWarning: boolean;
}

export interface SaleEntryInput {
  saleDate: string;
  productName: string;
  category?: string;
  quantity: number;
  unitPrice?: string;
  discount?: string;
  totalAmount?: string;
  customerName?: string;
  customerPhone?: string;
  paymentMethod?: string;
}

export async function createSaleEntry(getToken: GetToken, businessId: string, entry: SaleEntryInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/entries/sales`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify(entry),
  }).then((response) => parseJsonOrThrow<EntryCreateResponse>(response));
}

export interface ExpenseEntryInput {
  expenseDate: string;
  category: string;
  vendor?: string;
  amount: string;
  description?: string;
}

export async function createExpenseEntry(getToken: GetToken, businessId: string, entry: ExpenseEntryInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/entries/expenses`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify(entry),
  }).then((response) => parseJsonOrThrow<EntryCreateResponse>(response));
}

export interface InventoryEntryInput {
  productName: string;
  category?: string;
  quantity: number;
  reorderLevel?: number;
  supplier?: string;
  costPrice?: string;
  sellingPrice?: string;
}

export async function createInventoryEntry(getToken: GetToken, businessId: string, entry: InventoryEntryInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/entries/inventory`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify(entry),
  }).then((response) => parseJsonOrThrow<EntryCreateResponse>(response));
}

// Document processing (v0.3) -- photograph a receipt/invoice, review the
// vision-extracted rows, confirm. Mirrors the CSV column-mapping review
// flow. See app/routers/documents.py, docs/decisions.md [2026-07-24].

export interface DocumentCreateResponse {
  uploadSessionId: string;
  status: UploadStatusValue;
}

export interface DocumentStatus {
  status: UploadStatusValue;
  progress: number;
  datasetType: string | null;
  extractedRows: Record<string, string>[] | null;
  overallConfidence: number | null;
}

export async function uploadDocument(getToken: GetToken, businessId: string, datasetType: string, image: File) {
  const formData = new FormData();
  formData.append("datasetType", datasetType);
  formData.append("image", image);

  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: formData,
  }).then((response) => parseJsonOrThrow<DocumentCreateResponse>(response));
}

export async function getDocumentStatus(getToken: GetToken, businessId: string, sessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/${sessionId}`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<DocumentStatus>(response));
}

export async function updateDocumentRows(
  getToken: GetToken,
  businessId: string,
  sessionId: string,
  extractedRows: Record<string, string>[]
) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify({ extractedRows }),
  }).then((response) => parseJsonOrThrow<DocumentStatus>(response));
}

export interface DocumentConfirmResponse {
  status: UploadStatusValue;
  duplicateWarning: boolean;
}

export async function confirmDocument(getToken: GetToken, businessId: string, sessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/${sessionId}/confirm`, {
    method: "POST",
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<DocumentConfirmResponse>(response));
}

export type InsightSeverity = "info" | "warning" | "critical";

// Shapes match app/signals.py's metrics dicts exactly -- see each
// detect_*'s docstring there. Used by the isXMetrics runtime guards in
// components/charts/InsightVisual.tsx to narrow Insight.metrics safely.
export interface RevenueTrendMetrics {
  recentWeekRevenue: number;
  priorWeekRevenue: number;
  pctChange: number;
}

export interface ExpenseSpikeMetrics {
  category: string;
  recentAmount: number;
  baselineAmount: number;
  pctChange: number;
}

export interface StockDepletionMetrics {
  productName: string;
  quantity: number;
  dailyVelocity: number;
  daysToStockout: number | null;
}

export interface InactiveCustomersMetrics {
  inactiveSinceDays: number;
  count: number;
  customers: unknown[];
}

export interface Insight {
  id: string;
  insightType: string;
  severity: InsightSeverity;
  title: string;
  body: string;
  // Not validated by Pydantic beyond dict[str, Any] on the backend
  // (schemas/insights.py) -- narrow this with the isXMetrics guards in
  // components/charts/InsightVisual.tsx before trusting a shape, rather
  // than a compile-time-only discriminated union.
  metrics: Record<string, unknown>;
  isRead: boolean;
  periodStart: string | null;
  periodEnd: string | null;
  createdAt: string;
}

export async function listInsights(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<Insight[]>(response));
}

export async function getUnreadInsightCount(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/unread-count`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<{ unreadCount: number }>(response));
}

export async function markInsightRead(getToken: GetToken, businessId: string, insightId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/${insightId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify({ read: true }),
  }).then((response) => parseJsonOrThrow<Insight>(response));
}

export async function runInsightsAnalysis(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/run`, {
    method: "POST",
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<{ status: string }>(response));
}

export interface BusinessFact {
  id: string;
  content: string;
  source: string;
  createdAt: string;
}

export async function listBusinessFacts(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/memory/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<BusinessFact[]>(response));
}

export async function deleteBusinessFact(getToken: GetToken, businessId: string, factId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/memory/${factId}`, {
    method: "DELETE",
    headers: await authHeaders(getToken),
  });
}

// WhatsApp channel linking (v0.6 slice 1) -- generate a short-lived code in
// the web app, text it from WhatsApp to link that number. See
// app/routers/channels.py, docs/decisions.md.

export interface LinkCodeResponse {
  code: string;
  expiresAt: string;
  whatsappNumber: string | null;
}

export async function createWhatsAppLinkCode(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/channels/whatsapp/link-code`, {
    method: "POST",
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<LinkCodeResponse>(response));
}

// v0.6 slice 2 (outbound infrastructure + proactive delivery): "off"
// (default, opt-in) never pushes; "immediate" sends a bundled message
// right after each analysis run that finds something new; "daily_digest"
// batches on its own schedule regardless of when analysis ran. See
// app/insight_delivery.py, docs/decisions.md.
export type NotificationFrequency = "off" | "immediate" | "daily_digest";

export interface ChannelIdentitySummary {
  id: string;
  channel: string;
  displayName: string | null;
  maskedExternalId: string;
  verifiedAt: string;
  notificationFrequency: NotificationFrequency;
}

export async function listChannels(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/channels/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ChannelIdentitySummary[]>(response));
}

export async function updateChannelFrequency(
  getToken: GetToken,
  businessId: string,
  channelIdentityId: string,
  notificationFrequency: NotificationFrequency
) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/channels/${channelIdentityId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify({ notificationFrequency }),
  }).then((response) => parseJsonOrThrow<ChannelIdentitySummary>(response));
}

export async function unlinkChannel(getToken: GetToken, businessId: string, channelIdentityId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/channels/${channelIdentityId}`, {
    method: "DELETE",
    headers: await authHeaders(getToken),
  });
}

// v0.7 slice 3 (roadmap.md "Inventory depth") -- current stock, read from
// the products/stock_movements ledger (app/routers/products.py), plus the
// plain read-only sales/expenses list views (app/routers/ledger.py). See
// docs/decisions.md [2026-09-14].

export interface Product {
  id: string;
  name: string;
  sku: string | null;
  category: string | null;
  quantity: number;
  baseUnit: string;
  reorderLevel: number | null;
  costPrice: string | null;
  sellingPrice: string | null;
  lowStock: boolean;
}

export async function listProducts(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/products/`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<Product[]>(response));
}

export interface ProductUpdateInput {
  sku?: string;
  category?: string;
  baseUnit?: string;
  reorderLevel?: number;
  costPrice?: string;
  sellingPrice?: string;
}

export async function updateProduct(getToken: GetToken, businessId: string, productId: string, update: ProductUpdateInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/products/${productId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify(update),
  }).then((response) => parseJsonOrThrow<Product>(response));
}

// A proposal, not an assignment -- nothing is written until the owner
// accepts it (into the Edit form's SKU field) and saves.
export async function getSuggestedSku(getToken: GetToken, businessId: string, productId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/products/${productId}/suggested-sku`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<{ sku: string }>(response));
}

// "sale" is deliberately not an option here -- a sale's stock movement
// comes from the sales-entry pipeline, not a direct manual adjustment.
export type AdjustmentReason = "restock" | "recount" | "loss" | "damage";

export interface StockAdjustmentResponse {
  id: string;
  productId: string;
  quantityDelta: number;
  reason: string;
  currentStock: number;
}

export async function createStockAdjustment(
  getToken: GetToken,
  businessId: string,
  productId: string,
  adjustment: { reason: AdjustmentReason; quantity: number; unitName?: string; note?: string }
) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/products/${productId}/stock-movements`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify(adjustment),
  }).then((response) => parseJsonOrThrow<StockAdjustmentResponse>(response));
}

export interface ProductUnit {
  id: string;
  unitName: string;
  conversionToBase: string;
  createdAt: string;
}

export async function declareProductUnit(
  getToken: GetToken,
  businessId: string,
  productId: string,
  unit: { unitName: string; conversionToBase: string | number }
) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/products/${productId}/units`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
    body: JSON.stringify(unit),
  }).then((response) => parseJsonOrThrow<ProductUnit>(response));
}

export interface SaleListItem {
  id: string;
  saleDate: string | null;
  productName: string | null;
  quantity: number | null;
  unitPrice: string | null;
  totalAmount: string | null;
  customerName: string | null;
  paymentMethod: string | null;
}

export async function listSales(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/sales`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<SaleListItem[]>(response));
}

export interface ExpenseListItem {
  id: string;
  expenseDate: string | null;
  category: string | null;
  vendor: string | null;
  amount: string | null;
  description: string | null;
}

export async function listExpenses(getToken: GetToken, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/expenses`, {
    headers: await authHeaders(getToken),
  }).then((response) => parseJsonOrThrow<ExpenseListItem[]>(response));
}
