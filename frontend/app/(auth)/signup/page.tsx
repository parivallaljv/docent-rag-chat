"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { toast } from "sonner";
import { getSupabaseBrowserClient } from "@/lib/supabaseClient";

/**
 * Maps Supabase's raw `signUp` error messages to friendlier, product-voiced
 * copy. Supabase's wording for a duplicate-email signup has shifted across
 * versions ("User already registered" vs "A user with this email address
 * has already been registered"), so we match on a loose substring instead
 * of the exact string.
 */
function mapSignupError(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes("already registered") || lower.includes("already exists")) {
    return "That email is already registered. Try signing in instead.";
  }
  return message;
}

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmationMessage, setConfirmationMessage] = useState<string | null>(
    null
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setConfirmationMessage(null);

    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setIsSubmitting(true);

    try {
      const supabase = getSupabaseBrowserClient();
      const { data, error: signUpError } = await supabase.auth.signUp({
        email,
        password,
      });

      if (signUpError) {
        toast.error(mapSignupError(signUpError.message));
        return;
      }

      if (data.session) {
        // Email confirmation is disabled on this Supabase project - the
        // user is already signed in.
        toast.success("Account created");
        router.push("/documents");
        router.refresh();
        return;
      }

      // Email confirmation is required before a session is issued.
      toast.success("Account created");
      setConfirmationMessage(
        "Check your inbox to confirm your email, then sign in."
      );
    } catch {
      toast.error("Something went wrong. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="rounded-xl bg-surface p-8 shadow-lg sm:p-10"
    >
      {confirmationMessage ? (
        <div className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-card">
              <span className="material-symbols-outlined text-xl">check</span>
            </div>
          </div>
          <h1 className="mt-4 font-heading text-xl font-semibold tracking-tight text-foreground">
            Check your inbox
          </h1>
          <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-muted">
            {confirmationMessage}
          </p>
          <Link
            href="/login"
            className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            <span aria-hidden>←</span>
            <span>Back to sign in</span>
          </Link>
        </div>
      ) : (
        <>
          <h1 className="font-heading text-xl font-semibold tracking-tight text-foreground">
            Create your account
          </h1>
          <p className="mt-1 text-base text-muted">
            Start chatting with your own documents in a couple of minutes.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-foreground"
              >
                Email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-lg bg-surface-muted px-3.5 text-base text-foreground outline-none transition-shadow placeholder:text-muted focus:bg-surface focus:shadow-[0_0_0_2px_rgb(var(--primary)),0_0_0_4px_rgb(var(--primary)/0.15)]"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-foreground"
              >
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-lg bg-surface-muted px-3.5 text-base text-foreground outline-none transition-shadow placeholder:text-muted focus:bg-surface focus:shadow-[0_0_0_2px_rgb(var(--primary)),0_0_0_4px_rgb(var(--primary)/0.15)]"
                placeholder="At least 8 characters"
              />
              <p className="mt-1.5 flex items-center gap-1 text-xs text-muted">
                <span className="material-symbols-outlined text-[14px]">info</span>
                At least 8 characters
              </p>
            </div>

            <div>
              <label
                htmlFor="confirmPassword"
                className="block text-sm font-medium text-foreground"
              >
                Confirm password
              </label>
              <input
                id="confirmPassword"
                name="confirmPassword"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-lg bg-surface-muted px-3.5 text-base text-foreground outline-none transition-shadow placeholder:text-muted focus:bg-surface focus:shadow-[0_0_0_2px_rgb(var(--primary)),0_0_0_4px_rgb(var(--primary)/0.15)]"
                placeholder="Re-enter your password"
              />
            </div>

            {error && (
              <p
                role="alert"
                className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-card transition-all hover:bg-primary-hover active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span>{isSubmitting ? "Creating account…" : "Create account"}</span>
              {!isSubmitting && (
                <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-muted">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-primary hover:underline">
              Sign in
            </Link>
          </p>
        </>
      )}
    </motion.div>
  );
}
