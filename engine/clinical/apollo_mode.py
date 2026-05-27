"""
clinical/apollo_mode.py — Apollo Reasoning Engine (Phase 6B + Phase 9 intent-aware)

Position in Phase 6 pipeline:
    ConstraintEngine.filter()["safe_options"]
        →  ApolloMode.decide(safe_options, patient)
        →  { "choice": str, "reason": str }

What Apollo does:
    Fast, instinct-driven selection of ONE best option from safe_options.
    Outputs 1–3 lines of reasoning. No hallucination — choice must exist
    verbatim in safe_options.

Priority order (highest first):
    1. Resistance match     — progression + T790M → Osimertinib T790M+
    2. CNS disease          — brain mets → CNS-active regimen
    3. Driver mutation      — EGFR/ALK/ROS1 matched targeted therapy
    4. High urgency         — disease_burden=high → fast_response tagged option
    5. IO preference        — PD-L1 high + no driver → IO monotherapy
    6. First safe option    — tiebreaker: first in safe_options list

What Apollo does NOT do:
    - Evaluate all options (→ Manhattan)
    - Return ranked list (→ Manhattan)
    - Access options outside safe_options
    - Hallucinate regimen names
    - Write to audit log directly

Rules:
    - MUST select from safe_options only
    - MUST return a result even if safe_options has 1 item
    - NEVER returns empty choice
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority scorer — higher = more preferred
# ---------------------------------------------------------------------------

def _score_option(option: dict, patient: dict) -> tuple[int, str]:
    """
    Returns (priority_score, reason_fragment) for a single safe option.
    Higher score = Apollo prefers this option.
    """
    tags         = option.get("tags", {})
    priority_tags = option.get("priority_tags", [])
    biomarkers   = patient.get("biomarkers") or {}
    regimen      = option.get("regimen", "")

    score  = 0
    reason = ""

    # ── Priority 1: Resistance match (progression + T790M) ──────────────
    # Highest priority — off-guideline choice in resistance context is dangerous
    egfr_t790m       = biomarkers.get("egfr_t790m", False)
    progression_type = patient.get("progression_type")
    if egfr_t790m and progression_type == "progression" and "T790M" in regimen:
        score  = 100
        reason = "T790M resistance mutation confirmed on progression — Osimertinib is guideline-mandated second-line"
        return score, reason

    # ── Priority 2: CNS disease → CNS-active ────────────────────────────
    brain_mets = patient.get("brain_mets", False)
    if brain_mets and "cns_coverage" in priority_tags:
        score  = 80
        reason = (
            "Brain metastases present — "
            f"{regimen} selected for confirmed CNS penetration"
        )
        if patient.get("brain_mets_symptomatic"):
            reason += " (symptomatic; CNS-active therapy urgent)"
        return score, reason

    # ── Priority 3: Driver mutation matched ─────────────────────────────
    driver_type = tags.get("driver_type", "NONE")
    if driver_type != "NONE":
        driver_lower = driver_type.lower()
        if f"driver_matched_{driver_lower}" in priority_tags:
            score = 60
            biomarker_map = {
                "EGFR": "EGFR mutation",
                "ALK":  "ALK rearrangement",
                "ROS1": "ROS1 fusion",
            }
            bm_label = biomarker_map.get(driver_type, driver_type)
            reason   = (
                f"{bm_label} confirmed — {regimen} is guideline-preferred "
                f"targeted therapy with superior PFS vs chemotherapy"
            )
            return score, reason

    # ── Priority 4: High urgency / fast response ─────────────────────────
    # IO+chemo combo gets higher score than IO mono at high burden
    if "fast_response" in priority_tags:
        is_io  = tags.get("IO", False)
        chemo  = tags.get("chemo", False)
        if is_io and chemo:
            score = 45
            reason = (
                f"High disease burden — {regimen} chemo-IO combination selected: "
                "rapid cytoreduction + immune activation superior to monotherapy at high burden"
            )
        else:
            score  = 40
            reason = (
                f"High disease burden — {regimen} selected for rapid response profile "
                "(IO or targeted agent preferred over chemotherapy alone at high burden)"
            )
        return score, reason

    # ── Priority 5: IO preference (PD-L1 high, no driver) ────────────────
    pd_l1  = biomarkers.get("pd_l1", 0) or 0
    burden = (patient.get("disease_burden") or "").lower()
    is_io  = tags.get("IO", False)
    chemo  = tags.get("chemo", False)

    if is_io and not chemo and float(pd_l1) >= 50 and burden != "high":
        # IO monotherapy — good at PD-L1 high when burden is not high
        score  = 20
        reason = (
            f"PD-L1 {pd_l1}% (≥50%) with no targetable driver mutation — "
            f"{regimen} monotherapy is KEYNOTE-024 standard of care"
        )
        return score, reason

    if is_io and chemo and burden == "high":
        # IO+chemo combo at high burden — explicit promotion
        score  = 25
        reason = (
            f"High disease burden + PD-L1 {pd_l1}% — {regimen} chemo-IO combination "
            "preferred for rapid cytoreduction alongside immune activation"
        )
        return score, reason

    # ── Priority 6: Tiebreaker ───────────────────────────────────────────
    score  = 1
    reason = f"{regimen} selected as highest-ranked guideline option for this patient profile"
    return score, reason



# ---------------------------------------------------------------------------
# Phase 9 — Intent modulation helpers
# ---------------------------------------------------------------------------

_INTENT_SCORE_DELTA = {
    # (intent, modality_key) → score_delta applied AFTER base scoring
    # aggressive: reward high-intensity combinations
    ("aggressive", "chemo_io"):   +12,
    ("aggressive", "chemo"):       +6,
    # de-escalation: reward low-intensity / oral; penalise chemo combos
    ("de-escalation", "oral"):     +15,
    ("de-escalation", "targeted"): +8,
    ("de-escalation", "chemo"):    -12,
    ("de-escalation", "chemo_io"): -15,
    # palliative: strongly reward minimal-toxicity; strongly penalise chemo
    ("palliative", "oral"):        +20,
    ("palliative", "supportive"):  +20,
    ("palliative", "targeted"):    +10,
    ("palliative", "chemo"):       -20,
    ("palliative", "chemo_io"):    -20,
}

_INTENT_REASON_SUFFIX = {
    "aggressive":    " [intent: aggressive — high-intensity regimen preferred]",
    "balanced":      "",
    "de-escalation": " [intent: de-escalation — reduced-intensity regimen preferred]",
    "palliative":    " [intent: palliative — minimal-toxicity regimen preferred]",
}


def _apply_intent_delta(
    score: int, reason: str, option: dict, intent: str
) -> tuple[int, str]:
    """
    Adjust Apollo score and reason based on Phase 9 treatment intent.

    Design rule: does NOT override high clinical-priority scores (>= 60),
    which correspond to driver-matched, CNS, or T790M paths where clinical
    evidence mandates the choice regardless of intent.

    Intent modulation only applies to the IO/chemo scoring tier and the
    tiebreaker tier, where clinical flexibility genuinely exists.
    """
    if score >= 60 or intent == "balanced" or not intent:
        return score, reason

    tags = option.get("tags", {})
    is_io = tags.get("IO", False)
    chemo = tags.get("chemo", False)
    modality_key = (
        "chemo_io"   if (chemo and is_io) else
        "chemo"      if chemo else
        "oral"       if option.get("oral", False) else
        "targeted"   if tags.get("driver_type", "NONE") != "NONE" else
        "supportive" if tags.get("supportive", False) else
        None
    )

    delta = _INTENT_SCORE_DELTA.get((intent, modality_key), 0)
    suffix = _INTENT_REASON_SUFFIX.get(intent, "")
    return score + delta, reason + suffix


# ---------------------------------------------------------------------------
# ApolloMode
# ---------------------------------------------------------------------------

class ApolloMode:
    """
    Fast, single-choice reasoning engine.

    Instantiated once. Stateless — all context comes from arguments.
    """

    def decide(
        self,
        safe_options: List[dict],
        patient: dict,
    ) -> Dict[str, Any]:
        """
        Select ONE best option from safe_options.

        Args:
            safe_options: ConstraintEngine output["safe_options"] — already filtered
            patient:      Phase 6 patient dict

        Returns:
            {
                "choice":       str,   # regimen name — always from safe_options
                "reason":       str,   # 1-3 line rationale
                "evidence":     str,   # guideline citation from the chosen option
                "priority_used": str,  # which priority rule fired
                "source":       "apollo"
            }
        """
        if not safe_options:
            logger.warning("ApolloMode.decide() called with empty safe_options")
            return {
                "choice":        "No safe option available",
                "reason":        "All policy options were blocked by clinical constraints. "
                                 "Clinical review required before proceeding.",
                "evidence":      "",
                "priority_used": "none",
                "source":        "apollo",
            }

        # Phase 9: read treatment intent injected by pipeline_integration
        intent = patient.get("intent", "balanced") or "balanced"

        # Score all options with base priority, then apply intent modulation
        scored = []
        for opt in safe_options:
            (base_score, base_reason) = _score_option(opt, patient)
            final_score, final_reason = _apply_intent_delta(
                base_score, base_reason, opt, intent
            )
            scored.append(((final_score, final_reason), opt))
        scored.sort(key=lambda x: x[0][0], reverse=True)

        (best_score, best_reason), best_opt = scored[0]

        # Map score to priority label for transparency
        priority_label = _score_to_priority_label(best_score)

        logger.info(
            "ApolloMode: selected='%s' priority='%s' score=%d",
            best_opt["regimen"], priority_label, best_score
        )

        return {
            "choice":        best_opt["regimen"],
            "reason":        best_reason,
            "evidence":      best_opt.get("evidence", ""),
            "priority_used": priority_label,
            "source":        "apollo",
        }


def _score_to_priority_label(score: int) -> str:
    if score >= 100:
        return "resistance_match"
    if score >= 80:
        return "cns_disease"
    if score >= 60:
        return "driver_mutation"
    if score >= 40:
        return "urgency"
    if score >= 20:
        return "io_preference"
    return "first_safe_option"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

APOLLO_MODE = ApolloMode()
