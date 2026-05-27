"""
engine/cancers/lung_progression.py — NSCLC Progression Detection (Phase 7B)

Used by timeline_engine.py ONLY.
Does NOT modify any NSCLC decision logic.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations
from typing import Tuple


def detect(state: dict) -> Tuple[bool, str]:
    """
    Detect NSCLC progression.

    Criteria (any one sufficient):
      1. Radiology: RECIST PD or new lesions
      2. Biomarker: Oligoprogression flag
      3. Clinical decline: ECOG worsening ≥2
    """
    # ── 1. Radiology ────────────────────────────────────────────────────
    radiology = state.get("radiology", {})
    if radiology.get("recist") == "PD":
        return True, "RECIST PD on imaging — systemic progression"
    if radiology.get("new_lesions"):
        return True, "New metastatic lesions detected"
    if radiology.get("oligoprogression"):
        return True, "Oligoprogression detected — limited site progression"

    # ── 2. Biomarker / resistance ────────────────────────────────────────
    if state.get("resistance_mutation"):
        return True, f"Acquired resistance mutation: {state['resistance_mutation']}"
    if state.get("progression_confirmed"):
        return True, "Progression confirmed via ctDNA or biopsy"

    # ── 3. Clinical decline ──────────────────────────────────────────────
    ecog_prev = state.get("ecog_prev")
    ecog_curr = state.get("ecog", state.get("ecog_status"))
    if ecog_prev is not None and ecog_curr is not None:
        if int(ecog_curr) - int(ecog_prev) >= 2:
            return True, f"ECOG worsened {ecog_prev}→{ecog_curr}"

    return False, "Stable disease — no progression criteria met"
