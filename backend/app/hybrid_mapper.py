"""
Hybrid mapping: runs the deterministic mapper first (fast, free), and
only calls the AI mapper for columns where deterministic confidence is
below the threshold or unresolved. Whichever method scores higher wins
as the primary suggestion; the other is kept in `alternatives` for
transparency in the review UI.
"""

from __future__ import annotations

from app.target_schema import TargetField
from app.deterministic_mapper import map_columns
from app import ai_mapper

AI_TRIGGER_THRESHOLD = 75.0  # deterministic confidence below this triggers an AI check


def build_hybrid_suggestions(
    columns: list[dict],  # [{"name": str, "sample_values": list}, ...]
    target_fields: list[TargetField],
) -> dict:
    source_names = [c["name"] for c in columns]
    deterministic = {s.source_column: s for s in map_columns(source_names, target_fields)}

    weak_columns = [
        c for c in columns if deterministic[c["name"]].confidence < AI_TRIGGER_THRESHOLD
    ]

    ai_results: dict = {}
    ai_available = True
    if weak_columns:
        ai_available = ai_mapper.is_ai_available()
        if ai_available:
            ai_results = ai_mapper.ai_match_columns(weak_columns, target_fields)

    final_suggestions = []
    for c in columns:
        det = deterministic[c["name"]]
        ai = ai_results.get(c["name"])

        if ai and ai.confidence > det.confidence:
            primary, other, other_label = ai, det, "deterministic"
        else:
            primary, other, other_label = det, ai, "ai"

        result = primary.to_dict()
        if other and other.target_field:
            result["alternatives"] = result.get("alternatives", []) + [
                {
                    "target_field": other.target_field,
                    "confidence": other.confidence,
                    "source": other_label,
                }
            ]
        final_suggestions.append(result)

    return {
        "suggestions": final_suggestions,
        "ai_available": ai_available,
    }