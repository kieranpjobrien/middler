"""Match the same team/event across providers (proposal §4.1, Phase 5).

Strategy, cheapest first (proposal §4.5):

1. exact match on a normalised name;
2. an explicit alias table (hand-maintained for the stubborn cases);
3. fuzzy match with ``rapidfuzz``;
4. an optional embedding fallback (``sentence-transformers``) for the hard cases.

Every result carries a confidence and a ``confident`` flag. Low-confidence matches
are surfaced, never silently actioned — and never used to place a bet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from middler.logging_setup import get_logger

log = get_logger(__name__)

_STOPWORDS = {"fc", "afc", "the", "club"}
_PUNCT = re.compile(r"[^a-z0-9\s]")


def normalise_name(name: str) -> str:
    """Lowercase, strip punctuation and common filler tokens, collapse spaces."""
    text = _PUNCT.sub(" ", name.lower())
    tokens = [t for t in text.split() if t not in _STOPWORDS]
    return " ".join(tokens)


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The outcome of matching a query name against candidates."""

    value: str | None  # the matched candidate (original form), or None
    score: float  # confidence in [0, 1]
    method: str  # "exact" | "alias" | "fuzzy" | "embedding" | "none"
    confident: bool  # met the threshold for its method


class EntityMatcher:
    """Aligns names across sources with graduated, confidence-gated strategies."""

    def __init__(
        self,
        aliases: dict[str, str] | None = None,
        fuzzy_threshold: float = 0.85,
        embed_threshold: float = 0.75,
        use_embeddings: bool = False,
    ) -> None:
        """Create a matcher.

        Args:
            aliases: Map of normalised name → canonical name for known hard cases.
            fuzzy_threshold: Minimum rapidfuzz score (0..1) to be ``confident``.
            embed_threshold: Minimum cosine similarity (0..1) for the fallback.
            use_embeddings: Enable the sentence-transformers fallback (optional dep).
        """
        self._aliases = {normalise_name(k): v for k, v in (aliases or {}).items()}
        self._fuzzy_threshold = fuzzy_threshold
        self._embed_threshold = embed_threshold
        self._use_embeddings = use_embeddings
        self._model: object | None = None

    def match(self, query: str, candidates: list[str]) -> MatchResult:
        """Match ``query`` against ``candidates`` using the cheapest viable method."""
        if not candidates:
            return MatchResult(None, 0.0, "none", False)
        norm_query = normalise_name(query)
        norm_map = {normalise_name(c): c for c in candidates}

        if norm_query in norm_map:
            return MatchResult(norm_map[norm_query], 1.0, "exact", True)

        if norm_query in self._aliases:
            target = normalise_name(self._aliases[norm_query])
            if target in norm_map:
                return MatchResult(norm_map[target], 1.0, "alias", True)

        best = process.extractOne(norm_query, list(norm_map), scorer=fuzz.WRatio)
        if best is not None:
            score = best[1] / 100.0
            if score >= self._fuzzy_threshold:
                return MatchResult(norm_map[best[0]], score, "fuzzy", True)

        if self._use_embeddings:
            embedded = self._embedding_match(query, candidates)
            if embedded is not None:
                return embedded

        # Best effort, but below threshold → not confident, must not be auto-actioned.
        fallback_score = (best[1] / 100.0) if best else 0.0
        fallback_value = norm_map[best[0]] if best else None
        return MatchResult(fallback_value, fallback_score, "fuzzy", False)

    def _embedding_match(self, query: str, candidates: list[str]) -> MatchResult | None:
        model = self._load_model()
        if model is None:
            return None
        from sentence_transformers import util

        q_emb = model.encode(query, convert_to_tensor=True)  # type: ignore[attr-defined]
        c_emb = model.encode(candidates, convert_to_tensor=True)  # type: ignore[attr-defined]
        scores = util.cos_sim(q_emb, c_emb)[0]
        best_idx = int(scores.argmax())
        score = float(scores[best_idx])
        return MatchResult(candidates[best_idx], score, "embedding", score >= self._embed_threshold)

    def _load_model(self) -> object | None:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                log.warning("embedding fallback requested but sentence-transformers is not installed (extra: embed)")
                self._use_embeddings = False
                return None
        return self._model
