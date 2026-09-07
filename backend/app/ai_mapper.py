"""
AI-assisted mapping engine using local sentence embeddings (no API key,
no per-call cost). Complements the deterministic mapper: it's invoked for
columns where deterministic matching is weak or unresolved, comparing
semantic meaning (not just string shape) between the source column and
each target field's name/description/aliases.

First call downloads a small (~80MB) model and needs internet once; after
that it runs fully offline. If the model can't load (no internet, no
disk space, etc.) this degrades gracefully -- callers should treat a
None return as "AI unavailable" and fall back to deterministic-only.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from functools import lru_cache

import numpy as np

from app.target_schema import TargetField

MODEL_NAME = "all-MiniLM-L6-v2"


@dataclass
class MappingSuggestion:
    source_column: str
    target_field: str | None
    method: str
    confidence: float
    evidence: str
    alternatives: list[dict]

    def to_dict(self):
        return asdict(self)


_model_load_failed = False


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def is_ai_available() -> bool:
    global _model_load_failed
    if _model_load_failed:
        return False
    try:
        _get_model()
        return True
    except Exception:
        _model_load_failed = True
        return False


def _target_text(tf: TargetField) -> str:
    parts = [tf.name.replace("_", " ")]
    if tf.description:
        parts.append(tf.description)
    parts.extend(tf.aliases)
    return ". ".join(parts)


def _source_text(column_name: str, sample_values: list) -> str:
    samples = ", ".join(str(v) for v in sample_values[:5])
    return f"{column_name}. Example values: {samples}" if samples else column_name


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def ai_match_columns(
    columns: list[dict],  # [{"name": str, "sample_values": list}, ...]
    target_fields: list[TargetField],
) -> dict[str, MappingSuggestion]:
    """Batch-embeds everything at once (much faster than per-column calls)."""
    if not columns:
        return {}

    model = _get_model()

    source_texts = [_source_text(c["name"], c.get("sample_values", [])) for c in columns]
    target_texts = [_target_text(tf) for tf in target_fields]

    source_embeddings = model.encode(source_texts)
    target_embeddings = model.encode(target_texts)

    results: dict[str, MappingSuggestion] = {}
    for i, col in enumerate(columns):
        scores = [
            (_cosine_sim(source_embeddings[i], target_embeddings[j]), tf)
            for j, tf in enumerate(target_fields)
        ]
        scores.sort(key=lambda x: x[0], reverse=True)
        top_score, top_field = scores[0]
        confidence = round(max(0.0, min(top_score, 1.0)) * 100, 1)

        alternatives = [
            {"target_field": tf.name, "confidence": round(s * 100, 1)}
            for s, tf in scores[1:4]
        ]

        desc = f' ("{top_field.description}")' if top_field.description else ""
        results[col["name"]] = MappingSuggestion(
            source_column=col["name"],
            target_field=top_field.name,
            method="ai",
            confidence=confidence,
            evidence=f"Semantic similarity to '{top_field.name}'{desc} scored {confidence}%.",
            alternatives=alternatives,
        )

    return results