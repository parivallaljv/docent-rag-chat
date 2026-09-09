"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { toast } from "sonner";
import { getSupabaseBrowserClient } from "@/lib/supabaseClient";

/**
 * Maps Supabase's raw `signInWithPassword` error messages to friendlier,
 * product-voiced copy.
 */
function mapLoginError(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes("invalid login credentials") || lower.includes("invalid credentials")) {
    return "Incorrect email or password. Try again or reset your password.";
  }
  if (lower.includes("email not confirmed") || lower.includes("confirm")) {
    return "Please confirm your email before signing in — check your inbox.";
  }
  return message;
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);

    try {
      const supabase = getSupabaseBrowserClient();
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (signInError) {
        toast.error(mapLoginError(signInError.message));
        return;
      }

      router.push("/documents");
      router.refresh();
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
      <h1 className="font-heading text-xl font-semibold tracking-tight text-foreground">
        Welcome back
      </h1>
      <p className="mt-1 text-base text-muted">
        Sign in to keep chatting with your documents.
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
          <div className="relative mt-1.5">
            <input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="h-10 w-full rounded-lg bg-surface-muted px-3.5 pr-10 text-base text-foreground outline-none transition-shadow placeholder:text-muted focus:bg-surface focus:shadow-[0_0_0_2px_rgb(var(--primary)),0_0_0_4px_rgb(var(--primary)/0.15)]"
              placeholder="••••••••"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted transition-colors hover:text-foreground"
            >
              <span className="material-symbols-outlined text-[18px]">
                {showPassword ? "visibility_off" : "visibility"}
              </span>
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-card transition-all hover:bg-primary-hover active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span>{isSubmitting ? "Signing in…" : "Sign in"}</span>
          {!isSubmitting && (
            <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
          )}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-muted">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="font-medium text-primary hover:underline">
          Sign up
        </Link>
      </p>
    </motion.div>
  );
}
