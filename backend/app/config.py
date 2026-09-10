"""Centralized thresholds so the mapper, UI copy, and docs stay in sync."""

HIGH_CONFIDENCE_THRESHOLD = 90.0  # >= this: auto-mapped, pre-accepted
LOW_CONFIDENCE_THRESHOLD = 60.0   # >= this (and < high): needs explicit review
                                   # below this, or no target: unresolved
AI_TRIGGER_THRESHOLD = 75.0       # deterministic confidence below this triggers an AI check
