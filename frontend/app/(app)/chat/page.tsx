import ChatWindow from "@/components/chat/ChatWindow";

interface ChatPageProps {
  searchParams: Promise<{ documentId?: string | string[]; chat?: string | string[] }>;
}

export default async function ChatPage({ searchParams }: ChatPageProps) {
  const params = await searchParams;
  const raw = params.documentId;
  const documentId = Array.isArray(raw) ? raw[0] : raw ?? null;

  const rawChat = params.chat;
  const chatId = Array.isArray(rawChat) ? rawChat[0] : rawChat ?? null;

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col">
      <div className="mb-4 flex shrink-0 items-center gap-3 rounded-xl bg-surface px-4 py-3 shadow-card">
        <span className="h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-primary" />
        <h1 className="font-heading text-xl font-semibold tracking-tight text-foreground">
          Chat
        </h1>
        <span className="h-5 w-px bg-border" />
        <p className="text-sm text-muted">
          {documentId
            ? "Scoped to a single document."
            : "Searching across all of your documents."}
        </p>
      </div>
      <ChatWindow documentId={documentId} initialChatId={chatId} />
    </div>
  );
}
