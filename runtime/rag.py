"""Load a document folder, chunk it, embed it, retrieve by cosine similarity.

ponytail: brute-force numpy cosine over all chunks. Fine for a few thousand chunks;
swap in FAISS if a corpus ever gets bigger than that.
"""
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np

from runtime import llm

TEXT_EXT = {".txt", ".md"}
# Identifiers worth exact matching: letters-hyphen-digits (WRT-0778, ISO-9001) or letters+3 digits (AB1234).
CODE = re.compile(r"\b[A-Za-z]{2,5}-\d{2,}[\w-]*\b|\b[A-Za-z]{2,5}\d{3,}\b")
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "embeddings"


def read_doc(path):
    """Return a document's text. PDFs go through pdftotext; CSVs become one line per row."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        return path.read_text(errors="replace")
    if ext == ".pdf":
        return strip_page_furniture(subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                                   capture_output=True, text=True, check=True).stdout)
    if ext == ".csv":
        with open(path, newline="", errors="replace") as f:
            rows = list(csv.DictReader(f))
        # Each row is self-describing so a single chunk can answer a lookup question.
        return "\n".join("; ".join(f"{k}: {v}" for k, v in row.items()) for row in rows)
    return None


_PAGE_NO = re.compile(r"(\bpage\s*\d+(\s*(of|/)\s*\d+)?\b|^\d+(\s*(of|/)\s*\d+)?$)", re.I)


def strip_page_furniture(text, max_words=12):
    """Drop running headers/footers: short lines that recur on at least half the pages of a
    form-feed-separated pdftotext dump. Pages are rejoined as paragraphs.

    Lines must recur exactly; numbers are ignored only inside page-number patterns ("Page 3",
    "3 of 12", a bare "3"), so table rows that differ by a number are never treated as furniture."""
    pages = [p for p in text.split("\f") if p.strip()]
    if len(pages) < 2:
        return text

    def norm(line):
        return _PAGE_NO.sub("<page>", " ".join(line.split()))
    counts = Counter(n for p in pages for n in {norm(l) for l in p.splitlines() if l.strip()})
    limit = max(2, len(pages) / 2)
    furniture = {n for n, c in counts.items() if c >= limit and len(n.split()) <= max_words}
    return "\n\n".join("\n".join(l for l in p.splitlines() if norm(l) not in furniture) for p in pages)


def load_folder(folder):
    """{filename: text} for every readable file in the folder (non-recursive, sorted)."""
    docs = {}
    for p in sorted(Path(folder).iterdir()):
        if p.is_file():
            text = read_doc(p)
            if text and text.strip():
                docs[p.name] = text
    return docs


def chunk_text(text, chunk_words=350, overlap=50):
    """Word-window chunks, preferring paragraph/line boundaries.

    Paragraphs (or CSV rows) are packed greedily up to chunk_words; a paragraph that is
    itself too long is split by words with `overlap` words carried between windows.
    """
    if overlap >= chunk_words:
        raise ValueError("overlap must be smaller than chunk_words")
    units = [u.strip() for u in text.replace("\r", "").split("\n\n") if u.strip()]
    if len(units) <= 1:  # CSV rows / single-block text: fall back to lines
        units = [u.strip() for u in text.splitlines() if u.strip()]
    chunks, cur = [], []
    for unit in units:
        words = unit.split()
        if len(words) > chunk_words:
            if cur:
                chunks.append(" ".join(cur))
                cur = []
            step = chunk_words - overlap
            for i in range(0, len(words), step):
                chunks.append(" ".join(words[i:i + chunk_words]))
                if i + chunk_words >= len(words):
                    break
            continue
        if len(cur) + len(words) > chunk_words and cur:
            chunks.append(" ".join(cur))
            cur = cur[-overlap:] if overlap else []
        cur.extend(words)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


class Index:
    """Chunks + a row-normalised embedding matrix. Embeddings are cached on disk by content hash."""

    def __init__(self, docs, chunk_words=350, overlap=50, embed_fn=llm.embed):
        self.embed_fn = embed_fn
        self.chunks = []
        for name, text in docs.items():
            for i, c in enumerate(chunk_text(text, chunk_words, overlap)):
                self.chunks.append({"id": f"{name}#{i}", "doc": name, "text": c})
        texts = [c["text"] for c in self.chunks]
        self.matrix = self._embed_cached(texts) if texts else np.zeros((0, 1))

    @classmethod
    def from_folder(cls, folder, chunk_words=350, overlap=50, embed_fn=llm.embed):
        return cls(load_folder(folder), chunk_words, overlap, embed_fn)

    def _embed_cached(self, texts):
        key = hashlib.sha256(json.dumps([llm.EMBED_MODEL, texts]).encode()).hexdigest()[:24]
        path = CACHE_DIR / f"{key}.npy"
        if path.exists() and self.embed_fn is llm.embed:
            return np.load(path)
        m = _normalise(np.array(self.embed_fn(texts, kind="document"), dtype=np.float32))
        if self.embed_fn is llm.embed:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(path, m)
        return m

    def search(self, query, k=4, min_score=0.0):
        """Top-k chunks, best first; each hit is a chunk dict plus `score` (and `exact` for code matches).

        Hybrid: chunks that contain an identifier from the query verbatim (a part number like WRT-0778)
        come first regardless of min_score, then cosine hits >= min_score fill the rest. Dense embeddings
        blur codes; live, the agent said a catalogue part number "is not in the documents"."""
        if not self.chunks:
            return []
        q = _normalise(np.array(self.embed_fn([query], kind="query"), dtype=np.float32))[0]
        scores = self.matrix @ q
        out, seen = [], set()
        for code in dict.fromkeys(CODE.findall(query)):
            rx = re.compile(rf"(?<![\w-]){re.escape(code)}(?![\w-])", re.I)
            for i, c in enumerate(self.chunks):
                if i not in seen and len(out) < k and rx.search(c["text"]):
                    out.append({**c, "score": round(float(scores[i]), 4), "exact": code})
                    seen.add(i)
        for i in np.argsort(-scores):
            if len(out) >= k or scores[i] < min_score:
                break
            if i not in seen:
                out.append({**self.chunks[i], "score": round(float(scores[i]), 4)})
        return out

    def get(self, chunk_id):
        return next((c for c in self.chunks if c["id"] == chunk_id), None)


def _normalise(m):
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)
