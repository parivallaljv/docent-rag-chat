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
  created_at: string;
}

export interface ChatCitation {
  id: string;
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
