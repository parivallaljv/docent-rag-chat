import { describe, expect, it } from "vitest";
import { buildAnswerMarkdown } from "./exportMarkdown";
import type { ChatCitation } from "./types";

function citation(overrides: Partial<ChatCitation> = {}): ChatCitation {
  return {
    id: "c1",
    document_id: "d1",
    filename: "report.pdf",
    page: 3,
    snippet: "Revenue grew 12%.",
    similarity: 0.9,
    ...overrides,
  };
}

describe("buildAnswerMarkdown", () => {
  it("renders question, answer and sources in order", () => {
    const md = buildAnswerMarkdown("What grew?", "Revenue grew [1].", [citation()]);
    expect(md).toBe(
      [
        "## Question\n\nWhat grew?",
        "## Answer\n\nRevenue grew [1].",
        "## Sources\n\n1. **report.pdf**, page 3\n   > Revenue grew 12%.",
      ].join("\n\n") + "\n"
    );
  });

  it("omits the question section when there is no question", () => {
    expect(buildAnswerMarkdown(null, "Hello", undefined)).toBe("## Answer\n\nHello\n");
  });

  it("omits the sources section for undefined or empty citations", () => {
    expect(buildAnswerMarkdown("q", "a", undefined)).not.toContain("## Sources");
    expect(buildAnswerMarkdown("q", "a", [])).not.toContain("## Sources");
  });

  it("trims the question and answer", () => {
    expect(buildAnswerMarkdown("  q  \n", "\n a \n", [])).toBe(
      "## Question\n\nq\n\n## Answer\n\na\n"
    );
  });

  it("uses the citation marker, falling back to the 1-based index", () => {
    const md = buildAnswerMarkdown("q", "a", [
      citation({ marker: 4, filename: "a.pdf" }),
      citation({ filename: "b.pdf" }),
    ]);
    expect(md).toContain("4. **a.pdf**");
    expect(md).toContain("2. **b.pdf**");
  });

  it("collapses snippet whitespace and drops an empty snippet line", () => {
    const md = buildAnswerMarkdown("q", "a", [
      citation({ snippet: "  line one\n\n  line   two " }),
      citation({ filename: "b.pdf", snippet: "   " }),
    ]);
    expect(md).toContain("   > line one line two");
    expect(md).toMatch(/2\. \*\*b\.pdf\*\*, page 3\n$/);
  });
});
