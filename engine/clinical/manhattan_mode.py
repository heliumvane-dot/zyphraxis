"""
clinical/manhattan_mode.py — Manhattan Reasoning Engine (Phase 6B + Phase 9 intent-aware)

Position in Phase 6 pipeline:
    ConstraintEngine.filter()["safe_options"]
        →  ManhattanMode.evaluate(safe_options, patient)
        →  [ ranked option dicts ]

What Manhattan does:
    Deep, structured evaluation of ALL safe_options.
    Returns every option with rank, reasoning, pros, cons, and safety notes.
    Rank 1 = most recommended.

Evaluation dimensions (per option):
    • Biomarker alignment     — driver match, T790M, PD-L1 threshold
    • ECOG fitness            — option suitability at patient ECOG level
    • Prior therapy           — cross-resistance risk, prior platinum use
    • Disease burden          — high burden favours fast-response agents
    • CNS coverage            — brain mets present → CNS penetration is factor
    • Organ function          — residual warnings from ConstraintEngine surfaced

Scoring model (additive, 0–100):
    driver_match:   +35   exact driver-targeted match
    cns_coverage:   +20   brain mets + CNS-active option
    fast_response:  +15   high burden + IO/targeted
    io_preference:  +10   PD-L1 ≥50%, no driver, IO mono
    io_combo:       +8    IO + chemo combo, any PD-L1
    ecog_penalty:   −10   chemo at ECOG ≥ 2
    prior_penalty:  −5    prior platinum exposure + platinum regimen again
    t790m_boost:    +35   T790M+ progression, T790M-specific option

Phase 9 intent modulation (additive, applied after base scoring):
    aggressive + chemo_io:      +12   reward high-intensity combos
    de-escalation + oral:       +15   reward low-burden oral agents
    de-escalation + chemo:      −12   penalise chemo in de-escalation
    palliative + oral/targeted: +20   strongly reward minimal-toxicity
    palliative + chemo:         −20   strongly penalise chemo in palliative

What Manhattan does NOT do:
    - Access options outside safe_options
    - Hallucinate regimen names or trial data
    - Call Apollo (parallel systems, not hierarchical)
    - Write to audit log directly

Rules:
    - MUST evaluate every option in safe_options
    - MUST assign unique ranks (ties broken by regimen name alphabetically)
    - NEVER returns empty list if safe_options is non-empty
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring dimensions
# ---------------------------------------------------------------------------

def _score_driver_match(option: dict, biomarkers: dict) -> Tuple[int, List[str], List[str]]:
    """Returns (score, pros, cons)."""
    tags        = option.get("tags", {})
    driver_type = tags.get("driver_type", "NONE")
    ptags       = option.get("priority_tags", [])

    if driver_type == "NONE":
        return 0, [], []

    driver_lower = driver_type.lower()
    if f"driver_matched_{driver_lower}" in ptags:
        bm_map = {
            "EGFR": ("EGFR mutation", "EGFR TKI superiority over chemotherapy: HR ~0.46 for PFS (FLAURA)"),
            "ALK":  ("ALK rearrangement", "ALK TKI superiority over chemotherapy: HR ~0.47 for PFS (ALEX)"),
            "ROS1": ("ROS1 fusion", "ROS1 TKI: ORR ~77%, intracranial activity confirmed (STARTRK-2)"),
        }
        bm_label, evidence_note = bm_map.get(driver_type, (driver_type, "Guideline-preferred targeted therapy"))
        return (
            35,
            [
                f"{bm_label} confirmed — driver-matched targeted therapy",
                evidence_note,
                "Avoids chemotherapy toxicity in biomarker-selected population",
            ],
            [],
        )

    # Driver option present but patient biomarker not confirmed — already filtered by policy,
    # but if present here it means biomarker was absent; mild penalty
    return 0, [], [f"Driver type {driver_type} option but patient biomarker status unconfirmed"]


def _score_t790m(option: dict, biomarkers: dict, progression_type: Optional[str]) -> Tuple[int, List[str], List[str]]:
    """T790M resistance — specific option boost."""
    egfr_t790m = biomarkers.get("egfr_t790m", False)
    regimen    = option.get("regimen", "")

    if egfr_t790m and progression_type == "progression" and "T790M" in regimen:
        return (
            35,
            [
                "T790M resistance mutation confirmed on liquid/tissue re-biopsy",
                "Osimertinib 3rd-gen TKI: AURA3 ORR 71% vs 31% chemotherapy",
                "Guideline-mandated choice at T790M+ progression (NCCN Cat 1)",
            ],
            [],
        )
    if egfr_t790m and "T790M" not in regimen and progression_type == "progression":
        return 0, [], ["T790M+ patient — non-T790M options de-prioritized"]

    return 0, [], []


def _score_cns(option: dict, patient: dict) -> Tuple[int, List[str], List[str]]:
    """Brain mets + CNS-active option."""
    brain_mets  = patient.get("brain_mets", False)
    symptomatic = patient.get("brain_mets_symptomatic", False)
    ptags       = option.get("priority_tags", [])
    tags        = option.get("tags", {})
    cns_active  = tags.get("CNS_active", False)

    if not brain_mets:
        return 0, [], []

    if "cns_coverage" in ptags and cns_active:
        pros = [
            "Brain metastases present — CNS-active agent with confirmed BBB penetration",
        ]
        if symptomatic:
            pros.append("Symptomatic CNS disease — CNS-active therapy addresses active intracranial disease")
        return 20, pros, []

    if not cns_active:
        cons = ["Limited CNS penetration — brain metastases may progress on this regimen"]
        if symptomatic:
            cons.append("Symptomatic brain mets — local CNS therapy (SRS/WBRT) should be discussed alongside")
        return 0, [], cons

    return 0, [], []


def _score_urgency(option: dict, patient: dict) -> Tuple[int, List[str], List[str]]:
    """High disease burden → fast-response priority."""
    burden = (patient.get("disease_burden") or "").lower()
    ptags  = option.get("priority_tags", [])

    if burden == "high" and "fast_response" in ptags:
        return (
            15,
            ["High disease burden — rapid response agent reduces risk of clinical deterioration"],
            [],
        )
    return 0, [], []


def _score_io(option: dict, biomarkers: dict, patient: dict = None) -> Tuple[int, List[str], List[str]]:
    """IO scoring — monotherapy vs combo, PD-L1 threshold awareness, burden context."""
    tags   = option.get("tags", {})
    is_io  = tags.get("IO", False)
    chemo  = tags.get("chemo", False)
    pd_l1  = float(biomarkers.get("pd_l1", 0) or 0)
    burden = ((patient or {}).get("disease_burden") or "").lower() if patient else ""

    if not is_io:
        return 0, [], []

    if not chemo:
        # IO monotherapy
        if pd_l1 >= 50:
            base_score = 10
            pros = [
                f"PD-L1 {pd_l1:.0f}% (≥50%) — pembrolizumab monotherapy KEYNOTE-024 standard",
                "Avoids chemotherapy toxicity in PD-L1 high population",
                "OS benefit vs chemotherapy: HR 0.62 at 5-year follow-up",
            ]
            cons = []
            # At high burden, monotherapy cytoreduction is slower — penalise
            if burden == "high":
                base_score -= 8
                cons.append(
                    "High disease burden — slower cytoreduction with monotherapy; "
                    "combination therapy provides faster tumour control"
                )
            return base_score, pros, cons
        else:
            return (
                2,
                ["IO agent — active in immunogenic tumours"],
                [f"PD-L1 {pd_l1:.0f}% (<50%) — monotherapy response rates lower; combination preferred"],
            )
    else:
        # IO + chemo combo
        base_score = 8
        pros = [
            "IO + chemotherapy combination: PFS and OS benefit regardless of PD-L1 level (KEYNOTE-189)",
            "Platinum doublet provides rapid cytoreduction alongside immune activation",
        ]
        cons = ["Additive toxicity vs monotherapy — requires adequate organ function and ECOG ≤2"]
        # At high burden, combination is strongly preferred — boost
        if burden == "high":
            base_score += 10
            pros.append(
                "High disease burden — chemo-IO combination provides faster and deeper response "
                "vs IO monotherapy; reduces risk of clinical deterioration"
            )
        return base_score, pros, cons


def _score_ecog_penalty(option: dict, patient: dict) -> Tuple[int, List[str], List[str]]:
    """Penalise chemo combinations at higher ECOG."""
    ecog  = patient.get("ecog") or 0
    tags  = option.get("tags", {})
    chemo = tags.get("chemo", False)

    if chemo and ecog >= 2:
        penalty = -10
        return (
            penalty,
            [],
            [
                f"ECOG {ecog} — chemotherapy toxicity risk elevated; "
                "intensive regimen requires careful benefit/risk assessment",
            ],
        )
    return 0, [], []


def _score_prior_platinum(option: dict, patient: dict) -> Tuple[int, List[str], List[str]]:
    """Penalise repeat platinum if prior platinum exposure documented."""
    prior = patient.get("prior_therapy") or ""
    tags  = option.get("tags", {})
    chemo = tags.get("chemo", False)
    regimen_lower = option.get("regimen", "").lower()

    if (
        chemo
        and "carboplatin" in regimen_lower or "cisplatin" in regimen_lower
        and "platinum" in str(prior).lower()
    ):
        return (
            -5,
            [],
            ["Prior platinum exposure — cumulative nephrotoxicity and neuropathy risk; "
             "assess cumulative AUC before re-challenge"],
        )
    return 0, [], []



# ---------------------------------------------------------------------------
# Phase 9 — Intent modulation scorer
# ---------------------------------------------------------------------------

_MANHATTAN_INTENT_DELTAS = {
    # (intent, modality_key) → score_delta
    ("aggressive", "chemo_io"):   +12,
    ("aggressive", "chemo"):       +6,
    ("de-escalation", "oral"):     +15,
    ("de-escalation", "targeted"): +8,
    ("de-escalation", "chemo"):    -12,
    ("de-escalation", "chemo_io"): -15,
    ("palliative", "oral"):        +20,
    ("palliative", "supportive"):  +20,
    ("palliative", "targeted"):    +10,
    ("palliative", "chemo"):       -20,
    ("palliative", "chemo_io"):    -20,
}

_INTENT_PROS = {
    "aggressive":    "Intent: aggressive — high-intensity regimen preferred per patient goal",
    "de-escalation": "Intent: de-escalation — lower-intensity regimen preferred",
    "palliative":    "Intent: palliative — minimal-toxicity / symptom-focused regimen preferred",
}

_INTENT_CONS = {
    "de-escalation": "Chemo-based regimen penalised: de-escalation intent warrants reduced intensity",
    "palliative":    "Chemo-based regimen penalised: palliative intent warrants minimal toxicity",
}


def _score_intent(option: dict, patient: dict) -> tuple[int, List[str], List[str]]:
    """
    Phase 9: intent-driven score adjustment.

    Reads patient["intent"] injected by PatientIntentEngine before decision layer.
    Does NOT override driver-matched or CNS priority — only modulates within the
    IO/chemo scoring tier where clinical flexibility exists.
    """
    intent = (patient.get("intent") or "balanced").lower()
    if intent == "balanced":
        return 0, [], []

    tags  = option.get("tags", {})
    is_io = tags.get("IO", False)
    chemo = tags.get("chemo", False)
    modality_key = (
        "chemo_io"  if (chemo and is_io) else
        "chemo"     if chemo else
        "oral"      if option.get("oral", False) else
        "targeted"  if tags.get("driver_type", "NONE") != "NONE" else
        "supportive" if tags.get("supportive", False) else
        None
    )

    delta = _MANHATTAN_INTENT_DELTAS.get((intent, modality_key), 0)
    pros: List[str] = []
    cons: List[str] = []

    if delta > 0 and intent in _INTENT_PROS:
        pros.append(_INTENT_PROS[intent])
    elif delta < 0 and intent in _INTENT_CONS:
        cons.append(_INTENT_CONS[intent])

    return delta, pros, cons


# ---------------------------------------------------------------------------
# ManhattanMode
# ---------------------------------------------------------------------------

class ManhattanMode:
    """
    Deep structured reasoning over all safe_options.

    Instantiated once. Stateless — all context comes from arguments.
    """

    # Ordered list of scoring functions — each returns (delta_score, pros, cons)
    _SCORERS = [
        lambda opt, pat, bm, pt: _score_driver_match(opt, bm),
        lambda opt, pat, bm, pt: _score_t790m(opt, bm, pt),
        lambda opt, pat, bm, pt: _score_cns(opt, pat),
        lambda opt, pat, bm, pt: _score_urgency(opt, pat),
        lambda opt, pat, bm, pt: _score_io(opt, bm, pat),
        lambda opt, pat, bm, pt: _score_ecog_penalty(opt, pat),
        lambda opt, pat, bm, pt: _score_prior_platinum(opt, pat),
        # Phase 9 — intent modulation (reads patient["intent"] injected by pipeline)
        lambda opt, pat, bm, pt: _score_intent(opt, pat),
    ]

    def evaluate(
        self,
        safe_options: List[dict],
        patient: dict,
    ) -> List[Dict[str, Any]]:
        """
        Evaluate ALL safe_options and return ranked list.

        Args:
            safe_options: ConstraintEngine output["safe_options"]
            patient:      Phase 6 patient dict

        Returns:
            List of option dicts, sorted by rank (1 = best), each containing:
            {
                "regimen":    str,
                "rank":       int,
                "score":      int,          # internal score (for transparency)
                "reasoning":  [str],        # ordered reasoning steps
                "pros":       [str],
                "cons":       [str],
                "safety":     [str],        # from ConstraintEngine warnings
                "evidence":   str,
                "source":     "manhattan"
            }
        """
        if not safe_options:
            logger.warning("ManhattanMode.evaluate() called with empty safe_options")
            return []

        biomarkers      = patient.get("biomarkers") or {}
        progression_type = patient.get("progression_type")

        scored: List[Tuple[int, str, dict]] = []

        for opt in safe_options:
            total_score, pros, cons, reasoning = self._score_option(
                opt, patient, biomarkers, progression_type
            )
            safety_notes = list(opt.get("warnings", []))  # from ConstraintEngine

            scored.append((
                total_score,
                opt.get("regimen", ""),   # tiebreaker
                {
                    "regimen":   opt.get("regimen", ""),
                    "score":     total_score,
                    "reasoning": reasoning,
                    "pros":      pros,
                    "cons":      cons,
                    "safety":    safety_notes,
                    "evidence":  opt.get("evidence", ""),
                    "source":    "manhattan",
                }
            ))

        # Sort: higher score first; alphabetical regimen name as tiebreaker
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Assign ranks
        result = []
        for rank, (_, _, data) in enumerate(scored, start=1):
            data["rank"] = rank
            result.append(data)

        logger.info(
            "ManhattanMode: evaluated %d options; top='%s' score=%d",
            len(result),
            result[0]["regimen"] if result else "none",
            result[0]["score"] if result else 0,
        )

        return result

    def _score_option(
        self,
        option:          dict,
        patient:         dict,
        biomarkers:      dict,
        progression_type: Optional[str],
    ) -> Tuple[int, List[str], List[str], List[str]]:
        """
        Run all scoring dimensions and accumulate score, pros, cons, reasoning.
        Returns (total_score, pros, cons, reasoning).
        """
        total = 0
        all_pros: List[str] = []
        all_cons: List[str] = []

        for scorer in self._SCORERS:
            delta, pros, cons = scorer(option, patient, biomarkers, progression_type)
            total     += delta
            all_pros  += pros
            all_cons  += cons

        # Build reasoning narrative from non-empty pros/cons
        reasoning: List[str] = []
        if all_pros:
            reasoning.append("Favourable factors: " + "; ".join(all_pros[:2]))
        if all_cons:
            reasoning.append("Considerations: " + "; ".join(all_cons[:2]))

        # Append organ function context if relevant
        organ = patient.get("organ_function") or {}
        if organ.get("renal") == "moderate":
            reasoning.append("Moderate renal impairment — dose adjustment may be required")
        if organ.get("hepatic") in ("moderate", "severe"):
            reasoning.append("Hepatic impairment — monitor LFTs; TKI dose adjustment per SmPC")

        # Ensure minimum score of 1 so all options are representable in rank
        total = max(1, total)

        return total, all_pros, all_cons, reasoning


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

MANHATTAN_MODE = ManhattanMode()
