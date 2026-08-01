"""In-process BM25 keyword index over chunk payloads.

The index is immutable: each (re)index publishes a fresh ``KeywordIndexState``
so searches never observe a half-built generation.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9+#]+(?:\.[a-z0-9+#]+)*")
_BM25_STOP_WORDS = frozenset(
    {
        "a", "about", "an", "and", "are", "at", "be", "been", "did", "do",
        "does", "for", "he", "her", "his", "how", "in", "is", "it", "me",
        "of", "on", "or", "tell", "that", "the", "their", "to", "was",
        "were", "what", "when", "where", "which", "who", "why", "will",
        "would", "with", "you", "your", "yours", "can", "could", "should",
        "i", "we", "they", "them", "this", "these", "those", "from", "by",
        "as", "if", "then", "than", "not", "no", "has", "have", "had",
        "am", "being", "please", "more", "s", "t",
    }
)


@dataclass(frozen=True)
class KeywordIndexState:
    """One immutable generation of the in-process BM25 index."""

    documents: tuple[dict[str, Any], ...]
    term_frequencies: tuple[Counter[str], ...]
    document_frequencies: Counter[str]
    average_document_length: float


EMPTY_INDEX = KeywordIndexState((), (), Counter(), 0.0)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def build_keyword_index(payloads: list[dict[str, Any]]) -> KeywordIndexState:
    """Build a BM25 index from Qdrant-compatible payloads."""
    term_frequencies: list[Counter[str]] = []
    document_frequencies: Counter[str] = Counter()

    total_tokens = 0
    for payload in payloads:
        tokens = tokenize(str(payload.get("text", "")))
        frequencies = Counter(tokens)
        term_frequencies.append(frequencies)
        document_frequencies.update(frequencies.keys())
        total_tokens += len(tokens)

    average_document_length = total_tokens / len(payloads) if payloads else 0.0
    return KeywordIndexState(
        documents=tuple(payloads),
        term_frequencies=tuple(term_frequencies),
        document_frequencies=document_frequencies,
        average_document_length=average_document_length,
    )


def bm25_rank(query: str, keyword_index: KeywordIndexState) -> list[tuple[int, float]]:
    """Return positive-score document indexes ranked by BM25."""
    query_tokens = list(
        dict.fromkeys(
            token for token in tokenize(query) if token not in _BM25_STOP_WORDS
        )
    )
    document_count = len(keyword_index.documents)
    if (
        not query_tokens
        or not document_count
        or keyword_index.average_document_length == 0
    ):
        return []

    scores = [0.0] * document_count
    for term in query_tokens:
        document_frequency = keyword_index.document_frequencies.get(term, 0)
        if document_frequency == 0:
            continue
        inverse_document_frequency = math.log(
            1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        for index, frequencies in enumerate(keyword_index.term_frequencies):
            term_frequency = frequencies.get(term, 0)
            if term_frequency == 0:
                continue
            document_length = sum(frequencies.values())
            length_normalization = 1 - 0.75 + (
                0.75 * document_length / keyword_index.average_document_length
            )
            scores[index] += inverse_document_frequency * (
                term_frequency * (1.5 + 1)
            ) / (term_frequency + 1.5 * length_normalization)

    return sorted(
        ((index, score) for index, score in enumerate(scores) if score > 0),
        key=lambda item: (-item[1], item[0]),
    )
