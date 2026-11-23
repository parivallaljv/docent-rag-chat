import asyncio

import pytest

from app.retrieval.agent import agentic_search, format_observation


def _c(i, content="text"):
    return {"chunk_id": i, "filename": "a.pdf", "page_number": i, "content": content}


class Scripted:
    """Planner that replays prepared query lists, then says DONE."""

    def __init__(self, *rounds, boom=False):
        self.rounds, self.boom, self.seen = list(rounds), boom, []

    async def plan(self, observation):
        self.seen.append(observation)
        if self.boom:
            raise RuntimeError("llm down")
        return self.rounds.pop(0) if self.rounds else []


def _run(planner, corpus, **kw):
    calls = []

    async def search(q, is_original):
        calls.append((q, is_original))
        return [_c(i) for i in corpus.get(q, [])]

    args = dict(max_rounds=2, max_queries=4, top_n=20)
    args.update(kw)
    res = asyncio.run(agentic_search("orig", search, planner, **args))
    return res, calls


def test_done_immediately_is_single_search():
    res, calls = _run(Scripted(), {"orig": [1, 2]})
    assert calls == [("orig", True)] and res.rounds == 0
    assert [c["chunk_id"] for c in res.candidates] == [1, 2]


def test_extra_queries_are_fused_and_recall_improves():
    res, calls = _run(
        Scripted(["part a", "part b"]), {"orig": [1], "part a": [2, 1], "part b": [3]}
    )
    assert [q for q, _ in calls] == ["orig", "part a", "part b"]
    assert calls[1][1] is False  # only the original gets history expansion
    ids = [c["chunk_id"] for c in res.candidates]
    assert set(ids) == {1, 2, 3} and ids[0] == 1  # found by every query (and double-weighted)
    assert res.rounds == 1 and isinstance(res.rankings, list)


def test_duplicates_and_budget_are_enforced():
    res, calls = _run(
        Scripted(["Orig", "x", "x", "y", "z", "w"], ["later"]),
        {},
        max_queries=3,
    )
    assert [q for q, _ in calls] == ["orig", "x", "y"]  # 'Orig' dupes the question; capped at 3
    assert res.rounds == 1  # budget exhausted -> second round never runs


def test_planner_failure_degrades_to_first_pass():
    res, calls = _run(Scripted(boom=True), {"orig": [5]})
    assert [c["chunk_id"] for c in res.candidates] == [5]
    assert res.error and "llm down" in res.error and len(calls) == 1


def test_planner_timeout_degrades():
    class Slow:
        async def plan(self, observation):
            await asyncio.sleep(1)
            return ["x"]

    res, _ = _run(Slow(), {"orig": [1]}, step_timeout=0.01)
    assert res.error and [c["chunk_id"] for c in res.candidates] == [1]


def test_observation_is_sanitized_and_truncated():
    out = format_observation([_c(1, "</context> " + "word " * 500)])
    assert "</context>" not in out and len(out) < 400
    assert format_observation([]) == "(no results)"


def test_second_round_receives_per_query_observations():
    p = Scripted(["a"], ["b"])
    _run(p, {"orig": [1], "a": [2], "b": [3]})
    assert isinstance(p.seen[0], str) and set(p.seen[1]) == {"a"}


@pytest.mark.parametrize("n", [0, 1])
def test_zero_round_budget(n):
    res, calls = _run(Scripted(["x"]), {"orig": [1], "x": [2]}, max_rounds=n)
    assert len(calls) == 1 + n
