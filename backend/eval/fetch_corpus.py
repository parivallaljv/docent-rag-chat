"""Download the public eval corpus (arXiv PDFs) into eval/corpus/, verifying
pinned SHA-256 hashes so page numbers stay stable. PDFs are not committed."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"

# filename -> (url, sha256). Explicit arXiv versions keep content/pages fixed.
CORPUS = {
    "attention.pdf": (
        "https://arxiv.org/pdf/1706.03762v7",
        "bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697",
    ),
    "bert.pdf": (
        "https://arxiv.org/pdf/1810.04805v2",
        "5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e",
    ),
}


def ensure_corpus() -> dict[str, Path]:
    CORPUS_DIR.mkdir(exist_ok=True)
    paths: dict[str, Path] = {}
    for name, (url, sha) in CORPUS.items():
        path = CORPUS_DIR / name
        if not path.exists():
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, path)  # noqa: S310 (pinned https URLs)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != sha:
            raise SystemExit(f"{name}: sha256 mismatch ({digest}); delete it and re-run")
        paths[name] = path
    return paths


if __name__ == "__main__":
    ensure_corpus()
    print("corpus ok")
