# Docent

A "chat with your documents" RAG (Retrieval-Augmented Generation) application. Upload PDFs, ask questions in natural language, and get streamed answers grounded in your own documents — every claim is backed by a clickable citation pointing to the exact page and passage it came from, with a real, data-driven relevance score.

Built end-to-end (auth, storage, ingestion pipeline, vector search, streaming chat, realtime UI) entirely on free tiers, as a portfolio project.

**Live demo:** https://docent-rag-chat.vercel.app
- Backend API: https://docent-rag-chat.onrender.com

Both are on free tiers, so the backend spins down after ~15 minutes idle — the first request after a while can take up to a minute to wake up (the chat UI shows this explicitly rather than looking frozen).

## Features

- **Document upload & ingestion** — drag-and-drop PDF upload direct to storage from the browser; a background pipeline extracts text, chunks it, embeds each chunk, and tracks per-document status (`pending` → `processing` → `ready`/`failed`) live in the UI via Supabase Realtime, no polling.
- **Retrieval-augmented chat** — ask a question across your whole library or scoped to a single document. The backend embeds the query, runs a pgvector similarity search, reranks candidates with Maximal Marginal Relevance (MMR) to balance relevance against redundancy, and only answers when it finds genuinely relevant context (an honest "I don't know" otherwise, never a hallucinated guess).
- **Real citations, not vibes** — every answer links back to the exact chunk(s) it was grounded in: source filename, page number, the actual excerpt, and a real cosine-similarity score rendered as an animated D3 gauge (not a decorative fake percentage).
- **Streaming chat over WebSocket** — token-by-token streaming with a proper turn lifecycle (connecting → waking-from-cold-start → streaming → done), mid-turn cancellation, and markdown rendering (headers, bold, lists, tables) for structured answers.
- **Cross-vendor LLM fallback** — the chat model automatically fails over across multiple Gemini models and, as a last resort, a completely different vendor (Groq) if every Gemini model is exhausted or degraded, bounded by a single shared latency budget rather than compounding per-model timeouts.
- **Authentication** — email/password auth via Supabase, with row-level security scoping every document and chat to its owner.
- **Polished, responsive UI** — Material-3-inspired design system (custom Tailwind tokens, Inter/Geist/JetBrains Mono type scale, Material Symbols icons), animated with Framer Motion, dark-mode aware.

## Tech stack

**Frontend**
- [Next.js 16](https://nextjs.org/) (App Router) + [React 19](https://react.dev/) + TypeScript
- [Tailwind CSS](https://tailwindcss.com/) for styling, [Framer Motion](https://motion.dev/) for animation
- [D3.js](https://d3js.org/) for the data-bound relevance gauge
- [react-markdown](https://github.com/remarkjs/react-markdown) + `remark-gfm` for rendering streamed markdown (tables, lists, bold) safely
- [Supabase JS](https://supabase.com/docs/reference/javascript) for auth, direct-to-storage uploads, and Realtime subscriptions
- Deployed on [Vercel](https://vercel.com/) (free tier)

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) (Python, async) with a native WebSocket endpoint for chat
- [asyncpg](https://github.com/MagicStack/asyncpg) + [pgvector](https://github.com/pgvector/pgvector) for storage and vector similarity search on Supabase's managed Postgres
- [google-genai](https://github.com/googleapis/python-genai) for Gemini chat generation and embeddings, with a direct `httpx` integration to Groq's OpenAI-compatible API as a cross-vendor fallback
- PyJWT for verifying Supabase-issued session tokens
- Deployed on [Render](https://render.com/) (free tier, Docker runtime)

**Infrastructure**
- [Supabase](https://supabase.com/) — Postgres (with `pgvector`), Auth, Storage, and Realtime, all on the free tier
- [Google Gemini API](https://ai.google.dev/) — chat generation (primary) and embeddings, free tier
- [Groq API](https://console.groq.com/) — chat generation (fallback vendor), free tier

## Architecture

```
┌─────────────┐        HTTPS / WSS         ┌──────────────┐
│   Next.js    │ ─────────────────────────▶ │   FastAPI     │
│  (Vercel)    │ ◀───────────────────────── │  (Render)     │
└─────┬───────┘                             └──────┬───────┘
      │ direct upload / auth / realtime            │
      ▼                                             ▼
┌─────────────────────────────────────────────────────────┐
│                        Supabase                          │
│   Auth · Storage (PDFs) · Postgres + pgvector · Realtime  │
└─────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                                     ┌───────────────────────────┐
                                     │  Gemini API (primary)      │
                                     │  Groq API (fallback vendor)│
                                     └───────────────────────────┘
```

The frontend talks to Supabase directly for auth, file uploads, and realtime document-status updates — the FastAPI backend is only in the loop for retrieval and generation (search, rerank, prompt assembly, streaming chat), which is why the WebSocket connects browser-to-backend directly rather than through Next.js.

## Project structure

```
frontend/    Next.js app (App Router, components, Supabase client, WS client)
backend/     FastAPI app (routers, retrieval pipeline, LLM clients, ingestion, tests)
supabase/    Postgres migrations (schema, RLS policies, storage policies, realtime)
```

## Getting started locally

### Prerequisites
- Node.js 20+, Python 3.11+
- A free [Supabase](https://supabase.com/) project (Postgres with the `pgvector` extension enabled)
- A free [Gemini API key](https://ai.google.dev/) and, optionally, a free [Groq API key](https://console.groq.com/keys)

### Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Supabase + Gemini (+ optional Groq) credentials
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local   # fill in your Supabase project URL/anon key + backend URL
npm run dev
```

### Database schema
Apply the SQL files in `supabase/migrations/` (in order) to your Supabase project via the SQL editor, or via the Supabase CLI (`supabase db push`) if you have it linked.

## Environment variables

See `backend/.env.example` and `frontend/.env.local.example` for the full list. At minimum you'll need: a Supabase project URL, service-role key, DB connection string, and JWT settings; a Gemini API key; and the frontend's `NEXT_PUBLIC_API_URL` pointing at wherever the backend is running.

## Deployment

- **Backend → Render**: a `render.yaml` (Docker-based, free tier) is included in `backend/` — connect the repo, set the root directory to `backend`, and fill in the env vars Render prompts for (marked `sync: false` in `render.yaml`, i.e. secrets you type in yourself).
- **Frontend → Vercel**: import the repo, set the root directory to `frontend`, and add the same environment variables from `.env.local.example` (pointing `NEXT_PUBLIC_API_URL` at your deployed Render backend).
