"use client";

import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { toast } from "sonner";
import { getSupabaseBrowserClient } from "@/lib/supabaseClient";
import { postDocument, callWithWakeIndicator } from "@/lib/api";

type UploadStatus = "uploading" | "waking" | "linking" | "done" | "error";

interface UploadItem {
  id: string;
  filename: string;
  status: UploadStatus;
  error?: string;
}

const STORAGE_BUCKET = "documents";
const MAX_FILE_BYTES = 25 * 1024 * 1024; // 25 MB

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function UploadDropzone() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  function updateItem(id: string, patch: Partial<UploadItem>) {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...patch } : item))
    );
  }

  async function uploadFile(file: File) {
    const id = createId();
    setItems((prev) => [
      { id, filename: file.name, status: "uploading" as const },
      ...prev,
    ]);

    if (!/\.(pdf|docx|md|markdown|txt|html?)$/i.test(file.name)) {
      const message = "Supported files: PDF, DOCX, Markdown, TXT, HTML.";
      updateItem(id, { status: "error", error: message });
      toast.error(`${file.name}: ${message}`);
      return;
    }

    if (file.size > MAX_FILE_BYTES) {
      const message = "File is larger than 25 MB.";
      updateItem(id, { status: "error", error: message });
      toast.error(`${file.name}: ${message}`);
      return;
    }

    try {
      const supabase = getSupabaseBrowserClient();
      const {
        data: { user },
        error: userError,
      } = await supabase.auth.getUser();

      if (userError || !user) {
        const message = "You must be signed in to upload.";
        updateItem(id, { status: "error", error: message });
        toast.error(message);
        return;
      }

      const storagePath = `${user.id}/${file.name}`;

      const { error: uploadError } = await supabase.storage
        .from(STORAGE_BUCKET)
        .upload(storagePath, file, {
          upsert: true,
          contentType: file.type || "application/octet-stream",
        });

      if (uploadError) {
        updateItem(id, { status: "error", error: uploadError.message });
        toast.error(`${file.name}: ${uploadError.message}`);
        return;
      }

      updateItem(id, { status: "linking" });

      await callWithWakeIndicator(
        () => postDocument({ storage_path: storagePath, filename: file.name }),
        () => updateItem(id, { status: "waking" })
      );

      updateItem(id, { status: "done" });
      toast.success(`${file.name} uploaded`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed.";
      updateItem(id, { status: "error", error: message });
      toast.error(`${file.name}: ${message}`);
    }
  }

  function processFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    Array.from(fileList).forEach((file) => {
      void uploadFile(file);
    });
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    processFiles(event.dataTransfer.files);
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    processFiles(event.target.files);
    event.target.value = "";
  }

  function dismissItem(id: string) {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl bg-surface px-6 py-12 text-center shadow-card transition-all ${
          isDragging ? "bg-primary/5 shadow-lg" : "hover:shadow-lg"
        }`}
      >
        <div
          className={`flex h-16 w-16 items-center justify-center rounded-2xl transition-transform ${
            isDragging ? "scale-110 bg-primary/20" : "bg-primary/10"
          }`}
        >
          <span className="material-symbols-outlined text-[32px] text-primary">
            cloud_upload
          </span>
        </div>
        <p className="mt-4 text-base font-medium text-foreground">
          Drag and drop a document here, or{" "}
          <span className="font-semibold text-primary underline decoration-primary/40 underline-offset-4">
            click to browse
          </span>
        </p>
        <p className="mt-1 text-sm text-muted">
          Up to 25 MB per file · PDF, DOCX, MD, TXT, HTML
        </p>
        <div className="mt-4 flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-3 py-1 text-xs font-medium text-muted">
            <span className="material-symbols-outlined text-[14px]">bolt</span>
            Automatic chunking &amp; embedding
          </span>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm"
          multiple
          className="hidden"
          onChange={handleInputChange}
        />
      </div>

      {items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => {
            const isInProgress =
              item.status === "uploading" ||
              item.status === "linking" ||
              item.status === "waking";
            return (
              <li
                key={item.id}
                className="rounded-xl bg-surface px-4 py-3 text-sm shadow-card"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-primary">
                      <span className="material-symbols-outlined text-[20px]">
                        picture_as_pdf
                      </span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-foreground">
                        {item.filename}
                      </p>
                      <p
                        className={`mt-0.5 text-xs ${
                          item.status === "error" ? "text-danger" : "text-muted"
                        }`}
                      >
                        {statusLabel(item)}
                      </p>
                    </div>
                  </div>
                  {(item.status === "done" || item.status === "error") && (
                    <button
                      type="button"
                      onClick={() => dismissItem(item.id)}
                      aria-label={`Dismiss ${item.filename}`}
                      className="shrink-0 rounded-full p-1 text-muted transition-colors hover:bg-surface-muted hover:text-foreground"
                    >
                      <span className="material-symbols-outlined text-[18px]">close</span>
                    </button>
                  )}
                </div>
                {isInProgress && (
                  <div
                    className="relative mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-muted"
                    role="progressbar"
                    aria-label={`Uploading ${item.filename}`}
                  >
                    <div className="h-full w-1/3 animate-indeterminate rounded-full bg-primary" />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function statusLabel(item: UploadItem): string {
  switch (item.status) {
    case "uploading":
      return "Uploading…";
    case "linking":
      return "Starting processing…";
    case "waking":
      return "Waking up the server… this can take up to a minute.";
    case "done":
      return "Uploaded — processing will update below.";
    case "error":
      return item.error ?? "Upload failed.";
  }
}

