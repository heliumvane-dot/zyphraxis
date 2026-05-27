"""
clinical/cancers/prostate/progression.py — Prostate Progression Detection (Phase 7B)
Research use only.
"""
from __future__ import annotations
from typing import Tuple


def detect(state: dict) -> Tuple[bool, str]:
    # PSA progression (PCWG3: ≥25% rise + ≥2 ng/mL above nadir)
    psa_nadir = float(state.get("psa_nadir", 0) or 0)
    psa_curr  = float(state.get("psa", state.get("psa_curr", 0)) or 0)
    if psa_nadir > 0 and psa_curr > 0:
        if psa_curr >= psa_nadir * 1.25 and (psa_curr - psa_nadir) >= 2.0:
            return True, f"PSA progression: {psa_curr:.1f} vs nadir {psa_nadir:.1f} (PCWG3 criteria)"

    # Radiologic progression
    radiology = state.get("radiology", {})
    if radiology.get("recist") == "PD" or radiology.get("new_bone_lesions"):
        return True, "Radiologic progression — new lesions or RECIST PD"

    # Clinical decline
    ecog_prev = state.get("ecog_prev")
    ecog_curr = state.get("ecog", state.get("ecog_status"))
    if ecog_prev is not None and ecog_curr is not None:
        if int(ecog_curr) - int(ecog_prev) >= 2:
            return True, f"ECOG worsened {ecog_prev}→{ecog_curr}"

    return False, "No progression criteria met"
