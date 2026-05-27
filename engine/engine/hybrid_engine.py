"""
hybrid_engine.py — Zyphraxis Phase 6C: Hybrid Engine

Arbitrates between Apollo (conservative) and Manhattan (aggressive) mode outputs
to produce a single, resistance-aware, CNS-aware, safety-constrained recommendation.

Priority order (highest → lowest):
  1. Resistance-matched (T790M, acquired resistance override)
  2. CNS-active (brain mets present)
  3. Driver mutation match (EGFR, ALK, ROS1, KRAS, etc.)
  4. Urgency-adjusted (tumour escape window)
  5. Default guideline (NCCN evidence level)

Inputs:
  apollo_output    — output dict from Apollo mode run
  manhattan_output — output dict from Manhattan mode run
  safe_options     — list of treatment dicts that passed safety/eligibility gates

Output:
  {
    "final_regimen": str,
    "line":          int,
    "confidence":    float  (0–1)
  }

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import math
import sys
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Priority constants (internal scoring — not exposed to callers)
# ---------------------------------------------------------------------------
_PRIORITY_RESISTANCE   = 100_000
_PRIORITY_CNS          = 10_000
_PRIORITY_DRIVER       = 1_000
_PRIORITY_URGENCY      = 100
_PRIORITY_EVIDENCE     = 10

_EVIDENCE_RANK = {"1A": 4, "1B": 3, "2A": 2, "2B": 1, "3": 0}

# CNS-penetrant drugs by name (substring match)
_CNS_ACTIVE_KEYWORDS = [
    "osimertinib", "alectinib", "lorlatinib", "brigatinib",
    "capmatinib", "tepotinib",
]

# Resistance-specific biomarker → preferred drug mapping
_RESISTANCE_MAP: Dict[str, str] = {
    "T790M":      "osimertinib",
    "C797S":      "lorlatinib",
    "G1202R":     "lorlatinib",
    "ALK_G1202R": "lorlatinib",
    "MET_amp":    "capmatinib",
}

# Driver mutation → preferred modality
_DRIVER_MODALITY: Dict[str, str] = {
    "EGFR": "targeted",
    "ALK":  "targeted",
    "ROS1": "targeted",
    "KRAS": "targeted",
    "BRAF": "targeted",
    "MET":  "targeted",
    "RET":  "targeted",
    "NTRK": "targeted",
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class HybridEngine:
    """
    Arbitrates between Apollo and Manhattan recommendations and selects
    the single most appropriate treatment for the patient.

    Usage:
        engine = HybridEngine()
        result = engine.select(
            apollo_output    = apollo_result,
            manhattan_output = manhattan_result,
            safe_options     = eligible_treatments,
            patient_context  = patient_dict,   # optional but strongly recommended
        )
    """

    def select(
        self,
        apollo_output:    Dict[str, Any],
        manhattan_output: Dict[str, Any],
        safe_options:     List[Dict[str, Any]],
        patient_context:  Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run the full hybrid arbitration pipeline.

        Returns:
            {
                "final_regimen": str,
                "line":          int,
                "confidence":    float,
                "_debug":        dict   # full scoring trace for JustificationEngine
            }
        """
        ctx = patient_context or {}

        if not safe_options:
            return self._no_path("No safe treatment options available after eligibility filtering.")

        # ── Step 1: Extract candidate names from each mode ───────────────
        apollo_name    = self._extract_regimen(apollo_output)
        manhattan_name = self._extract_regimen(manhattan_output)

        # ── Step 2: Score every safe option by priority rules ────────────
        scored = []
        for t in safe_options:
            score, reasons = self._priority_score(t, ctx, apollo_name, manhattan_name)
            scored.append({
                "treatment":  t,
                "score":      score,
                "reasons":    reasons,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        # ── Step 3: Validate Apollo == Hybrid (failure condition guard) ──
        winner        = scored[0]
        final_name    = winner["treatment"]["name"]
        final_line    = winner["treatment"].get("line_of_therapy", 1)
        confidence    = self._compute_confidence(scored)

        # Agreement flag — use substring matching to handle name variants
        # (e.g. "Pembrolizumab monotherapy" in Phase 6A vs "Pembrolizumab" in catalogue)
        def _names_agree(a: Optional[str], b: Optional[str]) -> bool:
            if not a or not b:
                return False
            a_l, b_l = a.lower(), b.lower()
            return a_l == b_l or a_l in b_l or b_l in a_l

        apollo_agrees    = _names_agree(apollo_name, final_name)
        manhattan_agrees = _names_agree(manhattan_name, final_name)

        # Phase 6 spec: Apollo must not contradict Hybrid unless overridden
        # by resistance or CNS priority.
        override_active = any(
            r in ("resistance_matched", "cns_active") for r in winner["reasons"]
        )
        if not apollo_agrees and not override_active:
            # Down-score: something is off; lower confidence to flag for review
            confidence = round(confidence * 0.75, 3)

        return {
            "final_regimen":    final_name,
            "line":             final_line,
            "confidence":       confidence,
            "_debug": {
                "ranked":           [
                    {"name": s["treatment"]["name"], "score": s["score"], "reasons": s["reasons"]}
                    for s in scored
                ],
                "apollo_name":      apollo_name,
                "manhattan_name":   manhattan_name,
                "apollo_agrees":    apollo_agrees,
                "manhattan_agrees": manhattan_agrees,
                "override_active":  override_active,
                "patient_context":  ctx,
            },
        }

    # -----------------------------------------------------------------------
    # Priority scoring
    # -----------------------------------------------------------------------

    def _priority_score(
        self,
        treatment:     Dict[str, Any],
        ctx:           Dict[str, Any],
        apollo_name:   Optional[str],
        manhattan_name: Optional[str],
    ) -> tuple[float, List[str]]:
        """
        Compute a priority score for a single treatment.
        Higher = better.  Returns (score, [reason_tags]).
        """
        score   = 0.0
        reasons: List[str] = []

        name = treatment.get("name", "").lower()

        # 1. Resistance match
        resistance_marker = ctx.get("resistance_mutation") or ctx.get("acquired_resistance")
        if resistance_marker:
            preferred = _RESISTANCE_MAP.get(resistance_marker, "")
            if preferred and preferred in name:
                score += _PRIORITY_RESISTANCE
                reasons.append("resistance_matched")

        # 2. CNS-active (brain mets)
        if ctx.get("brain_mets") or ctx.get("cns_disease"):
            if any(k in name for k in _CNS_ACTIVE_KEYWORDS):
                score += _PRIORITY_CNS
                reasons.append("cns_active")

        # 3. Driver mutation match
        driver = (ctx.get("driver_mutation") or ctx.get("mutation") or "").upper()
        if driver and driver in _DRIVER_MODALITY:
            required_bm = treatment.get("required_biomarkers", {})
            if driver in required_bm:
                score += _PRIORITY_DRIVER
                reasons.append("driver_mutation_match")

        # 3b. PD-L1 high + no driver → IO positively rewarded (line-matched only)
        pdl1      = ctx.get("pdl1", 0) or 0
        no_driver = not driver
        line_req  = ctx.get("line", 1) or 1
        if (pdl1 >= 50 and no_driver
                and treatment.get("modality") == "immuno"
                and treatment.get("line_of_therapy", 1) == line_req):
            score += _PRIORITY_DRIVER * 2  # strong boost for PD-L1-selected IO
            reasons.append("pdl1_high_io_eligible")

        # 4. IO rejection for EGFR+ patients (spec requirement)
        # If patient has EGFR and treatment is IO → heavy penalty
        biomarkers = ctx.get("biomarkers", {})
        egfr_positive = str(biomarkers.get("EGFR", "")).lower() in ("positive", "mutated", "true", "yes")
        if egfr_positive and treatment.get("modality") == "immuno":
            score -= _PRIORITY_DRIVER * 5  # IO rejected for EGFR+
            reasons.append("io_rejected_egfr_positive")

        # 5. Urgency (tumour escape window pressure)
        escape_h = ctx.get("tumor_escape_h", 500)
        if escape_h < 168:  # < 1 week
            # Prefer faster-acting regimens
            duration = treatment.get("duration_h", 500)
            if duration < escape_h:
                score += _PRIORITY_URGENCY
                reasons.append("urgency_adjusted")

        # 6. Evidence level
        ev = _EVIDENCE_RANK.get(treatment.get("evidence_level", ""), 0)
        score += ev * _PRIORITY_EVIDENCE
        if ev >= 3:
            reasons.append("guideline_1A_1B")

        # 7. Consensus bonus — if both modes agree
        if apollo_name == treatment["name"] and manhattan_name == treatment["name"]:
            score += _PRIORITY_EVIDENCE * 5
            reasons.append("both_modes_agree")
        elif apollo_name == treatment["name"]:
            score += _PRIORITY_EVIDENCE * 2
            reasons.append("apollo_agrees")
        elif manhattan_name == treatment["name"]:
            score += _PRIORITY_EVIDENCE
            reasons.append("manhattan_agrees")

        # 8. Biomarker match bonus
        if treatment.get("biomarker_match"):
            score += _PRIORITY_EVIDENCE * 3
            reasons.append("biomarker_match")

        # 9. Prior therapy line enforcement
        line_requested = ctx.get("line", 1) or 1
        if treatment.get("line_of_therapy", 1) != line_requested:
            score -= _PRIORITY_EVIDENCE * 2
            reasons.append("line_mismatch")

        return score, reasons

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _extract_regimen(self, mode_output: Dict[str, Any]) -> Optional[str]:
        """Pull the selected regimen name from a mode output dict."""
        if not mode_output:
            return None
        # Support both flat and nested structures
        for key in ("final_regimen", "regimen", "name", "treatment"):
            val = mode_output.get(key)
            if isinstance(val, str) and val:
                return val
            if isinstance(val, dict):
                return val.get("name")
        # Try nested plan
        plan = mode_output.get("plan", {})
        if isinstance(plan, dict):
            return plan.get("regimen") or plan.get("name")
        return None

    def _compute_confidence(self, scored: List[Dict]) -> float:
        """
        Confidence = normalised gap between top and runner-up scores.
        Clipped to [0.0, 1.0].
        """
        if len(scored) < 2:
            return 0.95 if scored else 0.0
        best   = scored[0]["score"]
        second = scored[1]["score"]
        gap    = best - second
        # Use a reference gap of 5 evidence tiers (50 pts) as the normalisation anchor.
        # A gap of 50 gives conf ~0.98; a gap of 20 gives ~0.8.
        ref_gap = _PRIORITY_EVIDENCE * 5
        raw     = gap / (ref_gap + abs(gap) * 0.1 + 1e-9)
        return round(max(0.0, min(1.0, raw)), 3)

    def _no_path(self, reason: str) -> Dict[str, Any]:
        return {
            "final_regimen": "NO_PATH",
            "line":          0,
            "confidence":    0.0,
            "_debug": {"reason": reason},
        }
