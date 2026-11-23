/**
 * Shared types used across the frontend for talking to Supabase (documents
 * table) and the FastAPI backend (chat + ingestion endpoints).
 */

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentRecord {
  id: string;
  user_id: string;
  filename: string;
  storage_path: string;
  status: DocumentStatus;
  page_count: number | null;
  error_message?: string | null;
  /** Auto-generated topic tags; absent until the tags migration is applied. */
  tags?: string[];
  created_at: string;
}

export interface ChatCitation {
  id: string;
  /** The [n] number the answer used for this source. */
  marker?: number;
  document_id: string;
  filename: string;
  page: number;
  snippet: string;
  /** Cosine similarity (0-1) between the query and this passage. */
  similarity: number;
}

export type ChatRole = "user" | "assistant";

export interface ChatHistoryTurn {
  role: ChatRole;
  content: string;
}

export interface ChatSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoredChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  citations: ChatCitation[] | null;
  created_at: string;
}

export type InsightKind = "summary" | "key_facts" | "quiz";

export interface SummaryResult {
  summary: string;
  bullets: string[];
}

export interface KeyFactsResult {
  facts: { fact: string; page: number | null }[];
}

export interface QuizQuestion {
  question: string;
  options: string[];
  answer_index: number;
  explanation: string;
  page: number | null;
}

export interface QuizResult {
  questions: QuizQuestion[];
}

export type InsightResponse =
  | { kind: "summary"; cached: boolean; result: SummaryResult }
  | { kind: "key_facts"; cached: boolean; result: KeyFactsResult }
  | { kind: "quiz"; cached: boolean; result: QuizResult };

export interface CritiqueClaim {
  claim: string;
  supported: boolean;
  /** The [n] excerpt number backing the claim, when there is one. */
  excerpt: number | null;
}

export type ChatWarning = "possible_prompt_leak" | "no_valid_citations";

export interface CitationsMeta {
  messageId?: string;
  warning?: ChatWarning | string;
}

/** A memory note the assistant proposes saving; nothing is stored until the
 * user approves it. */
export interface MemoryProposal {
  id: string;
  action: "save_memory_note";
  text: string;
}

export type ProposalStatus = "saved" | "rejected" | "expired" | "failed";

export type ProposalDecision = "approve" | "reject";

export interface CompareSource {
  filename: string;
  page: number;
  snippet: string;
}

export interface CompareResponse {
  document_a: string;
  document_b: string;
  topic: string;
  similarities: string[];
  differences: string[];
  sources: CompareSource[];
}

export interface UsageDay {
  day: string;
  turns: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}

export interface UsageResponse {
  days: number;
  totals: {
    turns: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: number;
  };
  daily: UsageDay[];
  note?: string;
}
