"use client";

import { useEffect } from "react";
import Link from "next/link";

/**
 * Error boundary for the authenticated (app) route group (/documents,
 * /chat). Next.js 16.3 stabilized the `retry` prop (previously
 * `unstable_retry`) in place of the older `reset` naming - see
 * node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md.
 */
export default function AppError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <div className="relative flex h-16 w-16 items-center justify-center">
        <div className="absolute inset-0 animate-ping rounded-full bg-warning/10" />
        <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-warning/10 shadow-card">
          <span className="material-symbols-outlined text-3xl text-warning">gpp_maybe</span>
        </div>
      </div>
      <h1 className="mt-4 font-heading text-xl font-semibold tracking-tight text-foreground">
        Something went wrong
      </h1>
      <p className="mt-2 text-base text-muted">
        An unexpected error interrupted this page. Your documents and
        conversations are unaffected — you can try again, or head back to
        your documents.
      </p>
      {error.digest && (
        <p className="mt-2 font-mono text-xs text-muted">Error reference: {error.digest}</p>
      )}
      <div className="mt-6 flex items-center gap-3">
        <button
          type="button"
          onClick={() => retry()}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2.5 text-base font-semibold text-primary-foreground shadow-card transition-colors hover:bg-primary-hover"
        >
          <span className="material-symbols-outlined text-[18px]">refresh</span>
          <span>Try again</span>
        </button>
        <Link
          href="/documents"
          className="rounded-lg bg-surface px-4 py-2.5 text-base font-medium text-foreground shadow-card transition-colors hover:bg-surface-muted"
        >
          Back to Documents
        </Link>
      </div>
    </div>
  );
}
