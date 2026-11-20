"""RAG evaluation harness. Run from backend/:  python -m eval.run_eval

Replays Docent's real retrieval path in memory (no database):
  pypdf parse -> chunker -> Gemini embeddings -> cosine top-N -> MMR top-K
and scores it against eval/dataset.jsonl. Each question's relevant pages are
resolved at run time by finding its `evidence` string in the PDF text, so the
labels survive chunker changes. Embeddings are cached in eval/.cache/.

  --generate   also run generation + LLM-judge faithfulness (uses LLM quota)
  --limit N    only the first N questions
  --compare F  fail (exit 1) if a metric drops more than --max-drop vs file F
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.ingestion.chunker import chunk_pages
from app.ingestion.embedder import embed_chunks, embed_query
from app.ingestion.parser import extract_pages
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.prompt import ChatTurn, build_prompt  # noqa: F401  (ChatTurn re-exported for ad-hoc use)
from app.retrieval.rerank import dot, mmr_rerank

from .bm25 import BM25
from .fetch_corpus import ensure_corpus
from .metrics import hit_at_k, mrr, ndcg_at_k, recall_at_k

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
RESULTS = HERE / "results"
K = settings.RERANK_TOP_K
METRIC_KEYS = ["hit@1", "hit@3", "hit@5", "recall@5", "mrr", "ndcg@5"]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _load_cache(name: str) -> dict:
    path = CACHE / name
    return json.loads(path.read_text()) if path.exists() else {}


def _save_cache(name: str, data: dict) -> None:
    CACHE.mkdir(exist_ok=True)
    (CACHE / name).write_text(json.dumps(data))


async def _backoff(fn, *args, tries: int = 6):
    """Retry on free-tier 429s (per-minute quotas), sleeping out the window."""
    for attempt in range(tries):
        try:
            return await fn(*args)
        except Exception as exc:  # noqa: BLE001
            if "RESOURCE_EXHAUSTED" not in str(exc) or attempt == tries - 1:
                raise
            m = re.search(r"retry in ([\d.]+)s", str(exc))
            wait = float(m.group(1)) + 2 if m else 40
            print(f"  rate limited; sleeping {wait:.0f}s")
            await asyncio.sleep(wait)


def _key(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


async def build_index(paths: dict[str, Path]):
    """Return (chunks, page_text) where chunks are dicts with doc/page/content/embedding."""
    cache = _load_cache("chunks.json")
    chunks: list[dict] = []
    page_text: dict[str, str] = {}
    for doc, path in paths.items():
        pages = list(extract_pages(path.read_bytes()))
        for n, text in pages:
            page_text[f"{doc}:{n}"] = _norm(text)
        text_chunks = chunk_pages(
            pages,
            target_tokens=settings.CHUNK_TARGET_TOKENS,
            overlap_ratio=settings.CHUNK_OVERLAP_RATIO,
        )
        cfg = (
            settings.EMBEDDING_MODEL,
            settings.EMBEDDING_TASK_TYPES,
            settings.CHUNK_TARGET_TOKENS,
            settings.CHUNK_OVERLAP_RATIO,
        )
        ckey = _key(doc, *cfg, *(c.content for c in text_chunks))
        if ckey not in cache:
            print(f"embedding {len(text_chunks)} chunks for {doc} ...")
            cache[ckey] = await _backoff(embed_chunks, [c.content for c in text_chunks])
            _save_cache("chunks.json", cache)
        for c, emb in zip(text_chunks, cache[ckey], strict=True):
            chunks.append(
                {"doc": doc, "page": c.page_number, "content": c.content, "embedding": emb}
            )
    return chunks, page_text


async def embed_queries(questions: list[str]) -> list[list[float]]:
    cache = _load_cache("queries.json")
    out = []
    for q in questions:
        k = _key(settings.EMBEDDING_MODEL, settings.EMBEDDING_TASK_TYPES, q)
        if k not in cache:
            cache[k] = await _backoff(embed_query, q)
        out.append(cache[k])
    _save_cache("queries.json", cache)
    return out


VARIANTS = ["dense", "dense+mmr", "bm25", "hybrid", "hybrid+mmr"]


def retrieve(
    chunks: list[dict], qvec: list[float], query: str, bm25: BM25
) -> dict[str, list[dict]]:
    """All retrieval variants for one query. dense+mmr mirrors the original app
    path; hybrid fuses cosine and BM25 with RRF like search.search() does."""
    lex_scores = bm25.scores(query)
    scored = [
        {**c, "idx": i, "similarity": dot(c["embedding"], qvec), "bm25": lex_scores[i]}
        for i, c in enumerate(chunks)
    ]
    n = settings.RETRIEVAL_TOP_N
    dense = sorted(scored, key=lambda c: c["similarity"], reverse=True)[:n]
    lex = [c for c in sorted(scored, key=lambda c: c["bm25"], reverse=True)[:n] if c["bm25"] > 0]
    hybrid = reciprocal_rank_fusion([dense, lex], key=lambda c: c["idx"], k=settings.RRF_K)[:n]

    def mmr(pool: list[dict]) -> list[dict]:
        return mmr_rerank(
            pool,
            embedding_fn=lambda c: c["embedding"],
            relevance_fn=lambda c: c["similarity"],
            top_k=K,
            lambda_mult=settings.MMR_LAMBDA,
        )

    return {
        "dense": dense[:K],
        "dense+mmr": mmr(dense),
        "bm25": lex[:K],
        "hybrid": hybrid[:K],
        "hybrid+mmr": mmr(hybrid),
        "hybrid_pool": hybrid,  # full fused pool (not scored) for the agent
    }


def score(ranked: list[dict], relevant: set[str]) -> dict[str, float]:
    keys = [f"{c['doc']}:{c['page']}" for c in ranked]
    return {
        "hit@1": hit_at_k(keys, relevant, 1),
        "hit@3": hit_at_k(keys, relevant, 3),
        "hit@5": hit_at_k(keys, relevant, 5),
        "recall@5": recall_at_k(keys, relevant, 5),
        "mrr": mrr(keys, relevant),
        "ndcg@5": ndcg_at_k(keys, relevant, 5),
    }


def _avg(rows: list[dict[str, float]]) -> dict[str, float]:
    return {k: round(statistics.mean(r[k] for r in rows), 4) for k in METRIC_KEYS}


JUDGE_PROMPT = """You are grading a RAG answer. Reply with ONLY compact JSON:
{{"faithful": 0 or 1, "correct": 0 or 1}}
faithful=1 if every claim in the ANSWER is supported by the CONTEXT.
correct=1 if the ANSWER contains the fact in KEY_FACT.

QUESTION: {q}
KEY_FACT: {fact}
CONTEXT:
{ctx}

ANSWER:
{ans}"""


async def _collect(prompt: str, system: str | None = None) -> str:
    from app.llm.gemini_client import stream_chat

    return "".join([t async for t in stream_chat(prompt, system_instruction=system)])


async def generation_scores(rows: list[dict]) -> dict[str, float]:
    faithful, correct, refused = [], [], 0
    for r in rows:
        assembled = build_prompt(
            r["question"], r["final"], similarity_threshold=settings.SIMILARITY_THRESHOLD
        )
        if isinstance(assembled, str):  # guardrail short-circuit
            refused += 1
            faithful.append(0)
            correct.append(0)
            continue
        answer = await _collect(assembled.prompt, assembled.system_instruction)
        ctx = "\n".join(c.content for c in assembled.citations)
        raw = await _collect(
            JUDGE_PROMPT.format(q=r["question"], fact=r["evidence"], ctx=ctx, ans=answer)
        )
        try:
            verdict = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except (AttributeError, json.JSONDecodeError):
            verdict = {"faithful": 0, "correct": 0}
        faithful.append(int(verdict.get("faithful", 0)))
        correct.append(int(verdict.get("correct", 0)))
    return {
        "faithfulness": round(statistics.mean(faithful), 4),
        "answer_correct": round(statistics.mean(correct), 4),
        "guardrail_refusals": refused,
    }


def print_table(results: dict[str, dict[str, float]]) -> None:
    print(f"\n{'variant':<14}" + "".join(f"{k:>10}" for k in METRIC_KEYS))
    for name, m in results.items():
        print(f"{name:<14}" + "".join(f"{m[k]:>10.3f}" for k in METRIC_KEYS))


def compare(current: dict, baseline_path: Path, max_drop: float, variant: str) -> list[str]:
    base = json.loads(baseline_path.read_text())["metrics"][variant]
    return [
        f"{k}: {current[k]:.3f} vs baseline {base[k]:.3f}"
        for k in METRIC_KEYS
        if current[k] < base[k] - max_drop
    ]


def resolve_relevant(d: dict, page_text: dict[str, str]) -> set[str]:
    """Pages containing any of the item's evidence. `evidence` is a string (searched in
    `doc`) or a list of strings / [doc, phrase] pairs for multi-hop items."""
    ev = d["evidence"] if isinstance(d["evidence"], list) else [d["evidence"]]
    relevant: set[str] = set()
    for e in ev:
        doc, phrase = (d["doc"], e) if isinstance(e, str) else e
        found = {p for p, t in page_text.items() if p.startswith(doc + ":") and _norm(phrase) in t}
        if not found:
            raise SystemExit(f"{d['id']}: evidence not found in {doc}: {phrase!r}")
        relevant |= found
    return relevant


async def run_agent(question, qvec, chunks, bm25, stats) -> list[dict]:
    """Agentic retrieval over the in-memory index (real Gemini planner)."""
    from app.retrieval.agent import GeminiPlanner, agentic_search

    async def search_fn(q: str, is_original: bool) -> list[dict]:
        vec = qvec if is_original else (await embed_queries([q]))[0]
        pool = retrieve(chunks, vec, q, bm25)["hybrid_pool"]
        return [
            {**c, "chunk_id": c["idx"], "filename": c["doc"], "page_number": c["page"]}
            for c in pool
        ]

    res = await agentic_search(
        question,
        search_fn,
        GeminiPlanner(question),
        max_rounds=settings.AGENT_MAX_ROUNDS,
        max_queries=settings.AGENT_MAX_QUERIES,
        top_n=settings.RETRIEVAL_TOP_N,
        rrf_k=settings.RRF_K,
        step_timeout=30.0,
    )
    stats["errors"] += bool(res.error)
    stats["extra_queries"] += len(res.queries) - 1
    return res.candidates[:K]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    ap.add_argument(
        "--agentic",
        action="store_true",
        help="also score the LLM-planner agentic variant (uses chat quota)",
    )
    ap.add_argument("--limit", type=int)
    ap.add_argument("--compare", type=Path)
    ap.add_argument(
        "--variant",
        default="hybrid",
        choices=VARIANTS,
        help="variant used for --generate and --compare",
    )
    ap.add_argument("--max-drop", type=float, default=0.05)
    ap.add_argument("--out", type=Path, help="results file (default results/<timestamp>.json)")
    args = ap.parse_args()

    dataset = [json.loads(line) for line in (HERE / "dataset.jsonl").read_text().splitlines()]
    dataset = dataset[: args.limit] if args.limit else dataset
    chunks, page_text = await build_index(ensure_corpus())
    qvecs = await embed_queries([d["question"] for d in dataset])

    bm25 = BM25([c["content"] for c in chunks])
    scored_variants = [*VARIANTS, *(["agentic"] if args.agentic else [])]
    rows, per = [], {v: [] for v in scored_variants}
    agent_stats = {"errors": 0, "extra_queries": 0}
    for d, qv in zip(dataset, qvecs, strict=True):
        relevant = resolve_relevant(d, page_text)
        ranked = retrieve(chunks, qv, d["question"], bm25)
        if args.agentic:
            ranked["agentic"] = await run_agent(d["question"], qv, chunks, bm25, agent_stats)
        for v in scored_variants:
            per[v].append(score(ranked[v], relevant))
        rows.append(
            {
                **d,
                "relevant": sorted(relevant),
                "final": ranked[args.variant],
                "scores": per[args.variant][-1],
            }
        )

    metrics = {v: _avg(per[v]) for v in scored_variants}
    print_table(metrics)
    hop = [i for i, d in enumerate(dataset) if d.get("multihop")]
    if hop and len(hop) < len(dataset):
        print(f"\nmulti-hop subset ({len(hop)} questions):")
        print_table({v: _avg([per[v][i] for i in hop]) for v in scored_variants})
    if args.agentic:
        print(f"agent: {agent_stats}")
    misses = [r["id"] for r in rows if r["scores"]["hit@5"] == 0]
    print(
        f"\nvariant for gate/generation: {args.variant}  questions: {len(rows)}  chunks: {len(chunks)}  hit@5 misses: {misses or 'none'}"
    )

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config": {
            "embedding_model": settings.EMBEDDING_MODEL,
            "chunk_target_tokens": settings.CHUNK_TARGET_TOKENS,
            "chunk_overlap_ratio": settings.CHUNK_OVERLAP_RATIO,
            "top_n": settings.RETRIEVAL_TOP_N,
            "top_k": K,
            "mmr_lambda": settings.MMR_LAMBDA,
        },
        "metrics": metrics,
        "per_question": [
            {
                "id": r["id"],
                "relevant": r["relevant"],
                "retrieved": [f"{c['doc']}:{c['page']}" for c in r["final"]],
                **r["scores"],
            }
            for r in rows
        ],
    }
    if args.generate:
        report["generation"] = await generation_scores(rows)
        print("generation:", report["generation"])

    RESULTS.mkdir(exist_ok=True)
    out = args.out or RESULTS / f"{report['timestamp'].replace(':', '')}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")

    if args.compare:
        regressions = compare(metrics[args.variant], args.compare, args.max_drop, args.variant)
        if regressions:
            print("REGRESSION:\n  " + "\n  ".join(regressions))
            return 1
        print("no regression vs", args.compare)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
