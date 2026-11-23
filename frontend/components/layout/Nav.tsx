"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { motion } from "motion/react";
import { getSupabaseBrowserClient } from "@/lib/supabaseClient";
import MemoryModal from "./MemoryModal";
import UsageModal from "./UsageModal";

interface NavProps {
  userEmail?: string | null;
}

const links = [
  { href: "/documents", label: "Documents" },
  { href: "/chat", label: "Chat" },
];

export default function Nav({ userEmail }: NavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [dialog, setDialog] = useState<"memory" | "usage" | null>(null);

  async function handleSignOut() {
    const supabase = getSupabaseBrowserClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  // Dialogs render outside <header>: its backdrop-blur would otherwise
  // become the containing block for their fixed positioning.
  return (
    <>
      <header className="sticky top-0 z-10 bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-8">
            <Link href="/documents" className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary font-heading text-sm font-semibold text-primary-foreground">
                D
              </div>
              <span className="font-heading text-lg font-semibold tracking-tight text-foreground">
                Docent
              </span>
            </Link>
            <nav className="flex items-center gap-1 rounded-xl bg-surface-muted/70 p-1">
              {links.map((link) => {
                const isActive = pathname.startsWith(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="relative rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors"
                  >
                    {isActive && (
                      <motion.div
                        layoutId="nav-active-indicator"
                        className="absolute inset-0 rounded-lg bg-primary shadow-card"
                        transition={{ type: "spring", stiffness: 380, damping: 32 }}
                      />
                    )}
                    <span
                      className={`relative z-10 ${
                        isActive
                          ? "text-primary-foreground"
                          : "text-muted hover:text-foreground"
                      }`}
                    >
                      {link.label}
                    </span>
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-4">
            {userEmail && (
              <span className="hidden text-sm text-muted sm:inline">
                {userEmail}
              </span>
            )}
            <div className="flex items-center gap-0.5">
              {(
                [
                  { key: "memory", icon: "psychology_alt", label: "Memory" },
                  { key: "usage", icon: "bar_chart", label: "Usage" },
                ] as const
              ).map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setDialog(item.key)}
                  title={item.label}
                  aria-label={item.label}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-muted hover:text-foreground"
                >
                  <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={handleSignOut}
              className="rounded-lg bg-surface px-3 py-1.5 text-sm font-medium text-foreground shadow-card transition-colors hover:bg-surface-muted"
            >
              Sign out
            </button>
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-card">
              <span className="material-symbols-outlined text-[18px]">person</span>
            </div>
          </div>
        </div>
      </header>
      {dialog === "memory" && <MemoryModal onClose={() => setDialog(null)} />}
      {dialog === "usage" && <UsageModal onClose={() => setDialog(null)} />}
    </>
  );
}
