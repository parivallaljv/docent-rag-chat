"use client";

import { useState } from "react";
import type { ChatSummary } from "@/lib/types";

interface ChatListProps {
  chats: ChatSummary[];
  activeId: string | null;
  disabled?: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function ChatList({
  chats,
  activeId,
  disabled,
  onSelect,
  onNew,
  onDelete,
}: ChatListProps) {
  const [open, setOpen] = useState(false);
  const active = chats.find((chat) => chat.id === activeId);

  return (
    <div className="relative bg-surface-muted/60 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-background"
        >
          <span className="material-symbols-outlined text-[18px] text-primary">forum</span>
          <span className="truncate">{active?.title || "Conversations"}</span>
          <span className="material-symbols-outlined text-[18px] text-muted">
            {open ? "expand_less" : "expand_more"}
          </span>
        </button>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onNew();
          }}
          disabled={disabled}
          className="flex shrink-0 items-center gap-1 rounded-lg bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span className="material-symbols-outlined text-[16px]">add</span>
          New chat
        </button>
      </div>
      {open && (
        <ul className="absolute inset-x-3 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-xl bg-surface p-1 shadow-card ring-1 ring-border">
          {chats.length === 0 && (
            <li className="px-3 py-4 text-center text-sm text-muted">No conversations yet.</li>
          )}
          {chats.map((chat) => (
            <li
              key={chat.id}
              className={`flex items-center gap-2 rounded-lg ${
                chat.id === activeId ? "bg-primary/10" : "hover:bg-surface-muted"
              }`}
            >
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  setOpen(false);
                  onSelect(chat.id);
                }}
                className="min-w-0 flex-1 px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-60"
              >
                <p className="truncate text-sm font-medium text-foreground">
                  {chat.title || "New chat"}
                </p>
                <p className="text-xs text-muted">{relativeTime(chat.updated_at)}</p>
              </button>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Delete ${chat.title || "conversation"}`}
                onClick={() => {
                  if (window.confirm("Delete this conversation? This can't be undone.")) {
                    onDelete(chat.id);
                  }
                }}
                className="mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-60"
              >
                <span className="material-symbols-outlined text-[18px]">delete</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
