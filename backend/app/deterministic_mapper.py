"""
Deterministic mapping engine.

Rule order: exact match -> alias match -> fuzzy match. First rule that
clears its threshold wins. This is intentionally a pure function (no DB,
no I/O) so it's easy to unit test and easy to later run side-by-side with
an AI-based mapper behind the same interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from rapidfuzz import fuzz

from app.target_schema import TargetField

FUZZY_THRESHOLD = 60  # below this, we don't even offer a fuzzy suggestion


@dataclass
class MappingSuggestion:
    source_column: str
    target_field: str | None
    method: str  # exact | alias | fuzzy | unresolved
    confidence: float  # 0-100
    evidence: str
    alternatives: list[dict]

    def to_dict(self):
        return asdict(self)


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text

def _fuzzy_score(source: str, target: TargetField) -> float:
    source_norm = _normalize(source)

    candidates = [target.name] + target.aliases

    # Best fuzzy score against name + aliases
    fuzzy_score = max(
        fuzz.token_sort_ratio(source_norm, _normalize(candidate))
        for candidate in candidates
    )

    # Include description as an additional signal
    description_score = fuzz.token_set_ratio(
        source_norm,
        _normalize(target.description)
    )

    # Find meaningful shared words
    source_words = set(source_norm.split())
    target_words = set()

    for candidate in candidates:
        target_words.update(_normalize(candidate).split())

    shared_words = source_words & target_words

    # Strong bonus for exact shared keywords
    keyword_bonus = min(len(shared_words) * 15, 30)

    # Combine signals
    score = (
        fuzzy_score * 0.7
        + description_score * 0.2
        + keyword_bonus
    )

    return min(score, 100.0)

def match_column(source_column_name: str, target_fields: list[TargetField]) -> MappingSuggestion:
    norm_source = _normalize(source_column_name)

    # 1. Exact match on field name
    for tf in target_fields:
        if _normalize(tf.name) == norm_source:
            return MappingSuggestion(
                source_column=source_column_name,
                target_field=tf.name,
                method="exact",
                confidence=100.0,
                evidence=f"Column name matches target field '{tf.name}' exactly.",
                alternatives=[],
            )

    # 2. Alias match
    for tf in target_fields:
        for alias in tf.aliases:
            if _normalize(alias) == norm_source:
                return MappingSuggestion(
                    source_column=source_column_name,
                    target_field=tf.name,
                    method="alias",
                    confidence=92.0,
                    evidence=f"Column name matches a known alias ('{alias}') of '{tf.name}'.",
                    alternatives=[],
                )

    # 3. Fuzzy match -- score against field name and every alias, take the best
    scored: list[tuple[float, TargetField, str]] = []

    for tf in target_fields:
        score = _fuzzy_score(source_column_name, tf)
        scored.append((score, tf, tf.name))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_score, top_field, _ = scored[0]

    if top_score >= FUZZY_THRESHOLD:
        alternatives = [
            {"target_field": tf.name, "confidence": round(score, 1)}
            for score, tf, _ in scored[1:4]
            if score >= FUZZY_THRESHOLD - 15
        ]
        return MappingSuggestion(
            source_column=source_column_name,
            target_field=top_field.name,
            method="fuzzy",
            confidence=round(top_score, 1),
            evidence=f"Closest fuzzy match to '{top_field.name}' (score {round(top_score, 1)}).",
            alternatives=alternatives,
        )

    # 4. Nothing cleared the bar
    return MappingSuggestion(
        source_column=source_column_name,
        target_field=None,
        method="unresolved",
        confidence=0.0,
        evidence="No exact, alias, or fuzzy match cleared the confidence threshold.",
        alternatives=[
            {"target_field": tf.name, "confidence": round(score, 1)} for score, tf, _ in scored[:3]
        ],
    )


def map_columns(source_column_names: list[str], target_fields: list[TargetField]) -> list[MappingSuggestion]:
    return [match_column(name, target_fields) for name in source_column_names]
