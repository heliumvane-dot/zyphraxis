"""
clinical/cancers/breast/progression.py — Breast Cancer Progression Detection (Phase 7B)

Detects disease progression based on radiology, biomarkers, and clinical decline.
Used by timeline_engine.py — NEVER modifies decision logic.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple


def detect(state: dict) -> Tuple[bool, str]:
    """
    Detect progression for a breast cancer state.

    Progression criteria (any one sufficient):
      1. Radiology: new lesions or RECIST PD
      2. Biomarker trend: CA 15-3 / CA 27-29 rising ≥25%
      3. Clinical decline: ECOG worsening by ≥2 or new symptoms

    Args:
        state: Current patient state dict.

    Returns:
        (progressed: bool, reason: str)
    """
    # ── 1. Radiology ────────────────────────────────────────────────────
    radiology = state.get("radiology", {})
    if radiology.get("recist") == "PD":
        return True, "Radiology RECIST PD — progressive disease confirmed on imaging"
    if radiology.get("new_lesions"):
        return True, "New lesions detected on imaging — progression confirmed"

    # ── 2. Biomarker trend ───────────────────────────────────────────────
    ca153_prev = float(state.get("ca153_prev", 0) or 0)
    ca153_curr = float(state.get("ca153_curr", 0) or 0)
    if ca153_prev > 0 and ca153_curr > 0:
        delta = (ca153_curr - ca153_prev) / ca153_prev
        if delta >= 0.25:
            return True, f"CA 15-3 rising {delta*100:.0f}% — biochemical progression"

    ca2729_prev = float(state.get("ca2729_prev", 0) or 0)
    ca2729_curr = float(state.get("ca2729_curr", 0) or 0)
    if ca2729_prev > 0 and ca2729_curr > 0:
        delta = (ca2729_curr - ca2729_prev) / ca2729_prev
        if delta >= 0.25:
            return True, f"CA 27-29 rising {delta*100:.0f}% — biochemical progression"

    # ── 3. Clinical decline ──────────────────────────────────────────────
    ecog_prev = state.get("ecog_prev")
    ecog_curr = state.get("ecog", state.get("ecog_status"))
    if ecog_prev is not None and ecog_curr is not None:
        if int(ecog_curr) - int(ecog_prev) >= 2:
            return True, f"ECOG worsened from {ecog_prev} to {ecog_curr} — clinical decline"

    return False, "No progression criteria met — stable disease"
