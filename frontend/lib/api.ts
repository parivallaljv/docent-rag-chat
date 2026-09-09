"use client";

import { getSupabaseBrowserClient } from "./supabaseClient";
import type { DocumentRecord } from "./types";

/**
 * Base URL of the FastAPI backend. Chat and document-ingestion requests go
 * straight from the browser to this URL - never through a Next.js API
 * route - so that a slow/streaming LLM response isn't subject to Vercel's
 * serverless function timeout.
 */
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getAccessToken(): Promise<string> {
  const supabase = getSupabaseBrowserClient();
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session) {
    throw new ApiError("You must be signed in to do that.", 401);
  }
  return data.session.access_token;
}

async function extractErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.clone().json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    // response wasn't JSON - fall through to status text below
  }
  return res.statusText || `Request failed with status ${res.status}`;
}

/**
 * Thin fetch wrapper that talks to the FastAPI backend and attaches the
 * current Supabase session's access token as a Bearer token.
 */
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (!res.ok) {
    throw new ApiError(await extractErrorMessage(res), res.status);
  }

  return res;
}

export interface PostDocumentPayload {
  storage_path: string;
  filename: string;
}

/**
 * Tells the backend that a new file has landed in Supabase Storage (the
 * upload itself already happened directly from the browser) so it can kick
 * off ingestion. Returns the created/updated document record.
 */
export async function postDocument(
  payload: PostDocumentPayload
): Promise<DocumentRecord> {
  const res = await apiFetch("/documents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return res.json();
}

/**
 * Fetches the current user's documents from the backend. DocumentList
 * prefers a direct Supabase Realtime subscription for live updates, but
 * this is used anywhere else the app needs a one-off snapshot (e.g. to
 * populate the "scope this chat to a document" selector).
 */
export async function getDocuments(): Promise<DocumentRecord[]> {
  const res = await apiFetch("/documents", { method: "GET" });
  return res.json();
}

/**
 * Races `task` against a timer. If `task` hasn't settled after `delayMs`,
 * `onWaking` fires once - used to surface a "waking up the server..."
 * message when the Render free-tier backend is cold-starting, without
 * affecting the eventual resolved/rejected value of `task`.
 */
export async function callWithWakeIndicator<T>(
  task: () => Promise<T>,
  onWaking: () => void,
  delayMs = 2000
): Promise<T> {
  let settled = false;
  const timer = setTimeout(() => {
    if (!settled) onWaking();
  }, delayMs);

  try {
    return await task();
  } finally {
    settled = true;
    clearTimeout(timer);
  }
}
