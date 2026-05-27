"""
clinical/cancers/colorectal/progression.py — Colorectal Progression Detection (Phase 7B)
Research use only.
"""
from __future__ import annotations
from typing import Tuple


def detect(state: dict) -> Tuple[bool, str]:
    radiology = state.get("radiology", {})
    if radiology.get("recist") == "PD":
        return True, "Radiology RECIST PD — progression confirmed"
    if radiology.get("new_lesions"):
        return True, "New lesions on imaging — progression confirmed"

    cea_prev = float(state.get("cea_prev", 0) or 0)
    cea_curr = float(state.get("cea_curr", 0) or 0)
    if cea_prev > 0 and cea_curr > 0:
        delta = (cea_curr - cea_prev) / cea_prev
        if delta >= 0.25:
            return True, f"CEA rising {delta*100:.0f}% — biochemical progression"

    ecog_prev = state.get("ecog_prev")
    ecog_curr = state.get("ecog", state.get("ecog_status"))
    if ecog_prev is not None and ecog_curr is not None:
        if int(ecog_curr) - int(ecog_prev) >= 2:
            return True, f"ECOG worsened {ecog_prev}→{ecog_curr} — clinical decline"

    return False, "No progression criteria met"
