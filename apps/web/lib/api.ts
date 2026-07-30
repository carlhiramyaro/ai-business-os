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

export interface TokenResponse {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
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

export function registerUser(fullName: string, email: string, password: string) {
  return fetch(`${API_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fullName, email, password }),
  }).then((response) => parseJsonOrThrow<AuthUser>(response));
}

export function loginUser(email: string, password: string) {
  return fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then((response) => parseJsonOrThrow<TokenResponse>(response));
}

export function getCurrentUser(accessToken: string) {
  return fetch(`${API_URL}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  }).then((response) => parseJsonOrThrow<AuthUser>(response));
}

function authHeaders(accessToken: string) {
  return { Authorization: `Bearer ${accessToken}` };
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

export function createBusiness(accessToken: string, businessName: string) {
  return fetch(`${API_URL}/api/v1/businesses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ businessName }),
  }).then((response) => parseJsonOrThrow<Business>(response));
}

export function listBusinesses(accessToken: string) {
  return fetch(`${API_URL}/api/v1/businesses/`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<Business[]>(response));
}

export interface UploadCreateResponse {
  uploadSessionId: string;
  status: string;
}

export function createUpload(
  accessToken: string,
  businessId: string,
  files: { sales: File; inventory: File; expenses: File }
) {
  const formData = new FormData();
  formData.append("sales", files.sales);
  formData.append("inventory", files.inventory);
  formData.append("expenses", files.expenses);

  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: formData,
  }).then((response) => parseJsonOrThrow<UploadCreateResponse>(response));
}

export interface UploadSessionSummary {
  id: string;
  status: string;
  uploadedAt: string;
}

export function listUploads(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/`, {
    headers: authHeaders(accessToken),
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

export function getUploadStatus(accessToken: string, businessId: string, uploadSessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}`, {
    headers: authHeaders(accessToken),
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

export function getColumnMappings(accessToken: string, businessId: string, uploadSessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}/column-mappings`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<ColumnMapping[]>(response));
}

export function updateColumnMapping(
  accessToken: string,
  businessId: string,
  uploadSessionId: string,
  mappingId: string,
  targetField: string
) {
  return fetch(
    `${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}/column-mappings/${mappingId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
      body: JSON.stringify({ targetField }),
    }
  ).then((response) => parseJsonOrThrow<ColumnMapping>(response));
}

export function confirmColumnMappings(accessToken: string, businessId: string, uploadSessionId: string) {
  return fetch(
    `${API_URL}/api/v1/businesses/${businessId}/uploads/${uploadSessionId}/column-mappings/confirm`,
    { method: "POST", headers: authHeaders(accessToken) }
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

export interface ReportDetail {
  periodStart: string;
  periodEnd: string;
  status: ReportStatus;
  summary: string | null;
  risks: string[];
  opportunities: string[];
  forecast: string | null;
  actionPlan: string[];
}

export interface ReportGenerateResponse {
  reportId: string;
  status: ReportStatus;
}

export function listReports(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<ReportSummary[]>(response));
}

export function generateReport(accessToken: string, businessId: string, periodStart: string, periodEnd: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ periodStart, periodEnd }),
  }).then((response) => parseJsonOrThrow<ReportGenerateResponse>(response));
}

export function getReport(accessToken: string, businessId: string, reportId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/${reportId}`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<ReportDetail>(response));
}

export function deleteReport(accessToken: string, businessId: string, reportId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/reports/${reportId}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
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

export function createConversation(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/chat/`, {
    method: "POST",
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<ConversationCreateResponse>(response));
}

export interface ChatToolCall {
  tool: string;
  arguments: Record<string, unknown>;
}

export function sendChatMessage(accessToken: string, businessId: string, conversationId: string, message: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/chat/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ message }),
  }).then((response) => parseJsonOrThrow<{ answer: string; toolCalls: ChatToolCall[] }>(response));
}

export function getConversation(accessToken: string, businessId: string, conversationId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/chat/${conversationId}`, {
    headers: authHeaders(accessToken),
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

export function createSaleEntry(accessToken: string, businessId: string, entry: SaleEntryInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/entries/sales`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
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

export function createExpenseEntry(accessToken: string, businessId: string, entry: ExpenseEntryInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/entries/expenses`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
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

export function createInventoryEntry(accessToken: string, businessId: string, entry: InventoryEntryInput) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/entries/inventory`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
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

export function uploadDocument(accessToken: string, businessId: string, datasetType: string, image: File) {
  const formData = new FormData();
  formData.append("datasetType", datasetType);
  formData.append("image", image);

  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: formData,
  }).then((response) => parseJsonOrThrow<DocumentCreateResponse>(response));
}

export function getDocumentStatus(accessToken: string, businessId: string, sessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/${sessionId}`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<DocumentStatus>(response));
}

export function updateDocumentRows(
  accessToken: string,
  businessId: string,
  sessionId: string,
  extractedRows: Record<string, string>[]
) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ extractedRows }),
  }).then((response) => parseJsonOrThrow<DocumentStatus>(response));
}

export interface DocumentConfirmResponse {
  status: UploadStatusValue;
  duplicateWarning: boolean;
}

export function confirmDocument(accessToken: string, businessId: string, sessionId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/documents/${sessionId}/confirm`, {
    method: "POST",
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<DocumentConfirmResponse>(response));
}

export type InsightSeverity = "info" | "warning" | "critical";

export interface Insight {
  id: string;
  insightType: string;
  severity: InsightSeverity;
  title: string;
  body: string;
  metrics: Record<string, unknown>;
  isRead: boolean;
  periodStart: string | null;
  periodEnd: string | null;
  createdAt: string;
}

export function listInsights(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<Insight[]>(response));
}

export function getUnreadInsightCount(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/unread-count`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<{ unreadCount: number }>(response));
}

export function markInsightRead(accessToken: string, businessId: string, insightId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/${insightId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ read: true }),
  }).then((response) => parseJsonOrThrow<Insight>(response));
}

export function runInsightsAnalysis(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/insights/run`, {
    method: "POST",
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<{ status: string }>(response));
}

export interface BusinessFact {
  id: string;
  content: string;
  source: string;
  createdAt: string;
}

export function listBusinessFacts(accessToken: string, businessId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/memory/`, {
    headers: authHeaders(accessToken),
  }).then((response) => parseJsonOrThrow<BusinessFact[]>(response));
}

export function deleteBusinessFact(accessToken: string, businessId: string, factId: string) {
  return fetch(`${API_URL}/api/v1/businesses/${businessId}/memory/${factId}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}
