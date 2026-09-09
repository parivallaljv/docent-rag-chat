"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";

// Placeholder fallbacks let the client construct successfully (no throw at
// import/build time) even when env vars are missing, e.g. in CI or before a
// real Supabase project has been provisioned. Any actual network call made
// with placeholder values will simply fail at request time, not at
// construction time.
const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

let browserClient: ReturnType<typeof createBrowserClient> | null = null;

/**
 * Returns a singleton Supabase client for use in Client Components. Safe to
 * call multiple times - the underlying client is only constructed once per
 * page load.
 */
export function getSupabaseBrowserClient() {
  if (!browserClient) {
    browserClient = createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);

    // Realtime's `postgres_changes` authorization is evaluated (via RLS)
    // against whatever JWT is attached to the Realtime websocket connection
    // itself -- this is a separate connection from the one auth.getSession()
    // manages, and is NOT kept in sync automatically. Without this, every
    // postgres_changes subscription against an RLS-protected table (e.g.
    // DocumentList's live status updates) connects and reports "SUBSCRIBED"
    // successfully, but silently receives zero events, because Realtime
    // evaluates the row-level policies as the anonymous role. This fires
    // once immediately with the current session (or null) and again on
    // every sign-in/sign-out/token refresh.
    browserClient.auth.onAuthStateChange((_event: AuthChangeEvent, session: Session | null) => {
      browserClient?.realtime.setAuth(session?.access_token ?? null);
    });
  }
  return browserClient;
}
