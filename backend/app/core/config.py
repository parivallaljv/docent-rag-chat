"""Application settings, loaded from environment variables / a local .env file.

Every field has a safe default so the app can be imported (and pure-logic
modules can be unit tested) even with no .env present and no live
credentials configured yet.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

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
    MMR_LAMBDA: float = 0.5
    # Empirically measured against real gemini-embedding-001 vectors (768-dim,
    # Matryoshka-truncated + re-normalized): on-topic queries against a seeded
    # test document scored ~0.65-0.70 cosine similarity, clearly off-topic
    # queries scored ~0.44-0.44 -- 0.55 sits in the gap with margin both ways.
    SIMILARITY_THRESHOLD: float = 0.55
    MAX_PROMPT_TOKENS: int = 4000
    HISTORY_TURNS: int = 5

    # --- Chunking ---
    CHUNK_TARGET_TOKENS: int = 500
    CHUNK_OVERLAP_RATIO: float = 0.15

    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def chat_model_fallbacks_list(self) -> List[str]:
        return [m.strip() for m in self.CHAT_MODEL_FALLBACKS.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
