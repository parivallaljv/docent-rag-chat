import Link from "next/link";
import Reveal from "@/components/landing/Reveal";
import HowItWorksDiagram from "@/components/landing/HowItWorksDiagram";

const steps = [
  {
    title: "Upload your PDFs",
    body: "Drag in a report, a contract, a research paper - it uploads straight to secure storage and starts processing immediately.",
  },
  {
    title: "Ask anything",
    body: "Chat in plain English, scoped to one document or across your whole library. Answers stream in as they're generated.",
  },
  {
    title: "Trust the citation",
    body: "Every answer links back to the exact source document and page number it came from, so you can verify it in seconds.",
  },
];

const features = [
  {
    title: "Grounded answers",
    body: "Responses are generated only from passages retrieved from your own documents, with page-level citations attached.",
  },
  {
    title: "Live processing status",
    body: "Watch a document move from pending to processing to ready in real time as it's chunked, embedded, and indexed.",
  },
  {
    title: "Streamed responses",
    body: "Tokens appear as the model generates them, with a clear indicator while a cold-started backend spins back up.",
  },
  {
    title: "Your data, your account",
    body: "Email + password auth with row-level security, so every document and conversation is scoped to your account only.",
  },
];

const featureIcons = ["fact_check", "sync", "stream", "shield"] as const;

export default function LandingPage() {
  return (
    <div className="flex-1 bg-background">
      <div className="mx-auto max-w-6xl px-6 pt-6">
        <header className="flex items-center justify-between rounded-xl bg-surface px-6 py-3 shadow-card">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary font-heading font-semibold text-primary-foreground">
              D
            </div>
            <span className="font-heading text-lg font-semibold tracking-tight text-foreground">
              Docent
            </span>
          </div>
          <nav className="flex items-center gap-2">
            <Link
              href="/login"
              className="rounded-lg px-4 py-2 text-sm font-medium text-muted transition-colors hover:text-foreground"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-card transition-all hover:bg-primary-hover active:scale-95"
            >
              <span>Get started</span>
              <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
            </Link>
          </nav>
        </header>
      </div>

      <main>
        <section className="mx-auto max-w-4xl px-6 pt-16 pb-16 text-center">
          <div className="inline-flex items-center gap-2 rounded-full bg-surface px-4 py-1.5 shadow-card">
            <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
            <span className="text-sm font-medium text-primary">
              Retrieval-augmented generation, done properly
            </span>
            <span className="material-symbols-outlined text-xs text-primary">verified</span>
          </div>
          <h1 className="mx-auto mt-6 max-w-3xl font-heading text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
            Chat with your documents.
            <br />
            Get answers you can{" "}
            <span className="text-primary">actually verify</span>.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted">
            Docent is a demo RAG application: upload PDFs, ask questions, and
            get streamed answers that cite the exact document and page they
            came from - no more taking a chatbot&apos;s word for it.
          </p>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/signup"
              className="flex items-center gap-2 rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-card transition-all hover:-translate-y-0.5 hover:bg-primary-hover active:translate-y-0"
            >
              <span className="material-symbols-outlined text-base">bolt</span>
              <span>Get started for free</span>
            </Link>
            <Link
              href="/login"
              className="flex items-center gap-1.5 rounded-lg bg-surface px-6 py-3 text-sm font-semibold text-foreground shadow-card transition-colors hover:bg-surface-muted"
            >
              <span>Sign in</span>
              <span className="material-symbols-outlined text-base text-muted">login</span>
            </Link>
          </div>
        </section>

        <section className="py-16">
          <div className="mx-auto max-w-6xl px-6">
            <div className="mb-12 text-center">
              <span className="text-xs font-semibold uppercase tracking-widest text-muted">
                How it works
              </span>
              <h2 className="mt-1.5 font-heading text-2xl font-semibold tracking-tight text-foreground">
                Three steps to verified knowledge retrieval
              </h2>
            </div>
            <div className="mb-10">
              <HowItWorksDiagram />
            </div>
            <div className="grid gap-6 sm:grid-cols-3">
              {steps.map((step, index) => (
                <Reveal key={step.title} delay={index * 0.12}>
                  <div className="flex h-full flex-col items-start rounded-xl bg-surface p-6 text-left shadow-card">
                    <div
                      className={`flex h-11 w-11 items-center justify-center rounded-full font-heading text-lg font-semibold shadow-card ${
                        index === 2
                          ? "bg-success/10 text-success"
                          : "bg-primary text-primary-foreground"
                      }`}
                    >
                      {index + 1}
                    </div>
                    <h3 className="mt-4 text-base font-semibold text-foreground">
                      {step.title}
                    </h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted">{step.body}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-10 text-center">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted">
              Architecture &amp; capabilities
            </span>
            <h2 className="mt-1.5 font-heading text-2xl font-semibold tracking-tight text-foreground">
              Built like a real product, not a demo hack
            </h2>
            <p className="mx-auto mt-3 max-w-2xl text-muted">
              Every piece here mirrors a decision you&apos;d actually make
              shipping a RAG app in production.
            </p>
          </div>
          <div className="grid gap-6 sm:grid-cols-2">
            {features.map((feature, index) => (
              <Reveal key={feature.title} delay={(index % 2) * 0.1}>
                <div className="h-full rounded-xl bg-surface p-6 shadow-card transition-shadow hover:shadow-lg">
                  <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-surface-muted text-primary">
                    <span className="material-symbols-outlined">{featureIcons[index]}</span>
                  </div>
                  <h3 className="text-base font-semibold text-foreground">{feature.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{feature.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-6 pb-24">
          <div className="mx-auto max-w-3xl rounded-xl bg-surface px-8 py-12 text-center shadow-lg">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <span className="material-symbols-outlined text-2xl">auto_stories</span>
            </div>
            <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
              Ready to try it on your own documents?
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-muted">
              Create a free account, upload a PDF, and start asking it
              questions in under a minute.
            </p>
            <div className="mt-8">
              <Link
                href="/signup"
                className="inline-flex items-center rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-card transition-all hover:-translate-y-0.5 hover:bg-primary-hover active:translate-y-0"
              >
                Create your account
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="rounded-xl">
        <div className="mx-auto max-w-6xl px-6 pb-10 text-center text-sm text-muted">
          <div className="rounded-xl bg-surface px-6 py-6 shadow-card">
            Docent is a portfolio project pairing a Next.js + Supabase frontend
            with a FastAPI + pgvector retrieval backend.
          </div>
        </div>
      </footer>
    </div>
  );
}
