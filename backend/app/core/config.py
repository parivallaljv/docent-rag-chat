"""Application settings, loaded from environment variables / a local .env file.

Every field has a safe default so the app can be imported (and pure-logic
modules can be unit tested) even with no .env present and no live
credentials configured yet.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Supabase ---
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_DB_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    SUPABASE_JWT_SECRET: str = ""
    # Supabase's issued JWTs carry this as the `aud` claim for normal user sessions.
    SUPABASE_JWT_AUD: str = "authenticated"
    SUPABASE_STORAGE_BUCKET: str = "documents"

    # --- Gemini ---
    GEMINI_API_KEY: str = ""
    # Pinned to a specific, currently-confirmed-working model rather than the
    # "-latest" alias: -latest silently resolves to whatever bleeding-edge
    # preview Google ships (currently gemini-3.8-flash), and the newest
    # preview in a lineup appears to carry the lowest introductory free-tier
    # quota (see CHAT_MODEL_FALLBACKS below) -- exactly what caused repeated
    # quota-exhaustion errors. gemini-3.6-flash is a step more mature and was
    # confirmed live (2026-09-07, direct API call) to still be fully
    # available. Re-pin manually if/when Google deprecates this model,
    # rather than switching back to an auto-updating alias.
    CHAT_MODEL: str = "gemini-3.6-flash"
    # Empirically confirmed (2026-09-07): Gemini's free-tier daily request
    # quota is enforced PER MODEL, not per API key/project -- sibling models
    # each have their own separate, independent daily counter. When
    # establishing a generation stream hits CHAT_MODEL's quota exhaustion,
    # gemini_client.stream_chat tries the next model in this list before
    # giving up, so a demo visitor usually never sees an error at all as long
    # as at least one model still has budget left for the day. The
    # auto-updating "-latest" alias is kept only as the final, last-resort
    # fallback (not the primary model -- see CHAT_MODEL above) since it's
    # otherwise the most likely of these to be quota-exhausted first.
    # Comma-separated, parsed like ALLOWED_ORIGINS below.
    CHAT_MODEL_FALLBACKS: str = "gemini-3.7-flash,gemini-flash-latest"
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIM: int = 768
    # Empirically measured (2026-09-07): a single model's real free-tier
    # daily cap is only ~20 requests/day (see CHAT_MODEL_FALLBACKS above) --
    # far below generic "~1500/day free tier" documentation, which appears to
    # describe older/stabler Flash versions rather than a newer preview model
    # this alias can resolve to. With the fallback chain in place, a chat
    # turn can succeed against any of 3 models (~60 combined requests/day
    # realistically available), so this soft guard is sized to that combined
    # ceiling rather than one model's individual cap. This guard exists so
    # the app fails with ITS OWN friendly 429 message before Google's raw
    # quota exhaustion error would otherwise surface via the generic
    # mid-stream error path. Re-measure if Google changes any of these
    # models' quotas or the -latest alias moves to a different model.
    GEMINI_DAILY_QUOTA: int = 50

    # --- Groq (cross-vendor chat fallback) ---
    # Optional: only used as a last-resort fallback after every configured
    # Gemini model has failed/timed out (see gemini_client.stream_chat).
    # Empty string means Groq is skipped entirely -- safe no-op default,
    # same pattern as GEMINI_API_KEY above. Get a free key (no credit card,
    # permanent free tier as of 2026) at console.groq.com/keys.
    GROQ_API_KEY: str = ""
    # llama-3.3-70b-versatile was deprecated 2026-06-17; this is Groq's own
    # recommended replacement. Re-check console.groq.com/docs/deprecations
    # before re-pinning, same lesson learned from CHAT_MODEL above.
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # --- CORS ---
    # Comma-separated list of origins allowed to call this API directly
    # (the Next.js frontend calls /chat cross-origin, never proxied, since
    # streaming would exceed Vercel's free-tier function timeout).
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # --- Retrieval / generation tuning ---
    RETRIEVAL_TOP_N: int = 20
    RERANK_TOP_K: int = 5
    # 1.0 = MMR off (pure relevance order). Measured on eval/dataset.jsonl:
    # MMR lowered hit@5 / MRR in every variant, so it is off by default.
    MMR_LAMBDA: float = 1.0
    # Gemini asymmetric embeddings (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY).
    # Existing chunks embedded without task types should be re-ingested.
    # Measured: no gain on eval/dataset.jsonl (hybrid hit@5 0.92 off vs 0.88
    # on), and enabling it means re-ingesting existing chunks -> off.
    EMBEDDING_TASK_TYPES: bool = False
    # Hybrid retrieval: fuse pgvector cosine with Postgres full-text search via
    # Reciprocal Rank Fusion. Requires migration 005 (content_tsv column).
    # Measured: hybrid MRR 0.69 vs dense 0.60, hit@5 0.92 vs 0.83.
    HYBRID_SEARCH: bool = True
    RRF_K: int = 60
    # Rewrite follow-up questions into standalone queries with one extra LLM
    # call (falls back to history concatenation on any failure).
    QUERY_REWRITE: bool = False
    # pgvector HNSW query-time breadth (pgvector default is 40).
    HNSW_EF_SEARCH: int = 100
    # Empirically measured against real gemini-embedding-001 vectors (768-dim,
    # Matryoshka-truncated + re-normalized): on-topic queries against a seeded
    # test document scored ~0.65-0.70 cosine similarity, clearly off-topic
    # queries scored ~0.44-0.44 -- 0.55 sits in the gap with margin both ways.
    SIMILARITY_THRESHOLD: float = 0.55
    MAX_PROMPT_TOKENS: int = 4000
    HISTORY_TURNS: int = 5

    # --- Agentic search ---
    # An LLM planner may issue extra refined/decomposed searches (multi-hop,
    # comparison questions). Costs >=1 extra LLM call per turn; off by default.
    AGENTIC_SEARCH: bool = False
    AGENT_MODEL: str = ""  # empty = CHAT_MODEL (+ its fallbacks)
    AGENT_MAX_ROUNDS: int = 2
    AGENT_MAX_QUERIES: int = 4  # total searches incl. the original question
    AGENT_STEP_TIMEOUT: float = 10.0
    # With AGENTIC_SEARCH on: "search" (query refinement), "tools" (multi-tool
    # loop: search/get_page/compare/calculate) or "plan" (plan-and-execute).
    # --- Retrieval upgrades (each measured in eval/; all default off) ---
    RERANKER: str = ""  # "" | "llm" (listwise LLM rerank of the fused candidates)
    RERANK_MODEL: str = ""
    RERANK_TIMEOUT_SECONDS: float = 15.0
    HYDE: bool = False  # embed an LLM-written hypothetical answer for dense search
    HYDE_MODEL: str = ""
    HYDE_TIMEOUT_SECONDS: float = 10.0
    CONTEXTUAL_CHUNKS: bool = False  # LLM context sentence prepended before embedding
    CONTEXT_MODEL: str = ""
    SEMANTIC_CACHE: bool = False  # reuse answers for near-identical single-turn questions
    SEMANTIC_CACHE_THRESHOLD: float = 0.95
    SEMANTIC_CACHE_TTL_SECONDS: float = 3600.0
    # --- Multimodal / memory features (default off unless noted) ---
    FIGURE_CAPTIONS: bool = False  # describe figures/tables with a vision model at ingestion
    FIGURE_MODEL: str = ""
    AUTO_TAGS: bool = False  # LLM topic tags per document after ingestion
    CHAT_SUMMARY: bool = False  # rolling summary of long chats
    USER_MEMORY: bool = True  # inject the user's own memory notes (no LLM cost)
    AGENT_MODE: str = "search"
    AGENT_MAX_STEPS: int = 3
    AGENT_MAX_TOOL_CALLS: int = 6
    # Critic: second LLM pass that flags unsupported claims in an answer.
    CRITIC_ENABLED: bool = False
    CRITIC_MODEL: str = ""
    CRITIC_TIMEOUT_SECONDS: float = 20.0

    # Model for structured features (summary/key facts/quiz); empty = CHAT_MODEL chain.
    INSIGHTS_MODEL: str = ""

    # --- Ingestion ---
    # Scanned PDFs (no text layer): transcribe with Gemini vision. Costs LLM quota.
    OCR_FALLBACK: bool = True
    OCR_MODEL: str = ""  # empty = INSIGHTS_MODEL, else the CHAT_MODEL chain
    OCR_TIMEOUT_SECONDS: float = 90.0
    # Per-attempt cap for structured (JSON-mode) generation; a slow model falls through.
    STRUCTURED_TIMEOUT_SECONDS: float = 60.0
    # On startup, re-run documents stuck pending/processing for longer than this.
    RECOVER_STUCK_ON_STARTUP: bool = True
    STUCK_DOCUMENT_MINUTES: int = 10

    # --- Operations ---
    LOG_FORMAT: str = "json"  # "json" | "text"
    # /metrics is only served when this is set, and requires
    # `Authorization: Bearer <token>`.
    METRICS_TOKEN: str = ""
    # Per-user chat limiter (in-memory, per process).
    PER_USER_RATE_LIMIT: int = 10
    PER_USER_RATE_WINDOW_SECONDS: int = 60
    # Query-embedding cache (in-memory, per process).
    EMBED_CACHE_SIZE: int = 512
    EMBED_CACHE_TTL_SECONDS: int = 3600

    # --- Chunking ---
    CHUNK_TARGET_TOKENS: int = 500
    CHUNK_OVERLAP_RATIO: float = 0.15

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def chat_model_fallbacks_list(self) -> list[str]:
        return [m.strip() for m in self.CHAT_MODEL_FALLBACKS.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
