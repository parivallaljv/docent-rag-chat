import type { ChatCitation } from "./types";

/** Builds a markdown document (question, answer, sources) for one answer. */
export function buildAnswerMarkdown(
  question: string | null,
  answer: string,
  citations: ChatCitation[] | undefined
): string {
  const parts: string[] = [];
  if (question) parts.push(`## Question\n\n${question.trim()}`);
  parts.push(`## Answer\n\n${answer.trim()}`);
  if (citations && citations.length > 0) {
    const items = citations.map((c, i) => {
      const snippet = c.snippet.replace(/\s+/g, " ").trim();
      return `${c.marker ?? i + 1}. **${c.filename}**, page ${c.page}${snippet ? `\n   > ${snippet}` : ""}`;
    });
    parts.push(`## Sources\n\n${items.join("\n")}`);
  }
  return parts.join("\n\n") + "\n";
}

export function downloadMarkdown(filename: string, content: string): void {
  if (typeof document === "undefined") return;
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
