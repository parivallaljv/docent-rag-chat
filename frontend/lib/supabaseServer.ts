import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

// Same placeholder-fallback rationale as lib/supabaseClient.ts: never throw
// at construction time just because real credentials haven't been wired up
// yet.
const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

/**
 * Creates a Supabase client for use in Server Components, Server Actions,
 * and Route Handlers. Reads/writes the auth session via Next.js's cookie
 * store so the session set by middleware.ts is available on the server.
 *
 * Must be called fresh on every request (cookies() is request-scoped), so
 * this is a factory function rather than a cached singleton.
 */
export async function createSupabaseServerClient() {
  const cookieStore = await cookies();

  return createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        } catch {
          // `setAll` is called from a Server Component when the session is
          // refreshed. This can be safely ignored as long as middleware.ts
          // is also refreshing the session (which it is - see
          // middleware.ts) - it's the middleware's cookie writes that
          // actually persist across requests.
        }
      },
    },
  });
}
