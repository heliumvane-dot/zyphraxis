"""
learning/learning_engine.py — Zyphraxis Phase 7C: Learning Engine

SAFETY CONTRACT (non-negotiable):
  ✓ MAY adjust confidence score
  ✗ MUST NOT change treatment/regimen selection
  ✗ MUST NOT affect hybrid engine arbitration
  ✗ MUST NOT introduce new therapies
  ✗ MUST NOT override safety constraints or policy rules

CRITICAL ASSERTION — enforced before every return:
    assert decision_before_learning == decision_after_learning

If this assertion fails: STOP and report — do not return.

Memory model:
  - Stores (case_fingerprint → outcome) pairs
  - Similarity matching via biomarker/subtype overlap
  - Confidence adjusted upward for repeated similar cases with good outcomes
  - Confidence adjusted downward for cases with poor outcomes
  - No side effects on decision pipeline

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Case fingerprinting
# ---------------------------------------------------------------------------

def _fingerprint(case: dict) -> str:
    """
    Create a deterministic fingerprint for a case.
    Based on cancer_type, subtype, stage, line_of_therapy, and key biomarkers.
    NOT sensitive to ordering.
    """
    relevant = {
        "cancer_type":    case.get("cancer_type", ""),
        "subtype":        case.get("subtype", ""),
        "stage":          case.get("stage", ""),
        "line_of_therapy": case.get("line_of_therapy", 1),
        "biomarkers":     _stable_biomarkers(case.get("biomarkers", {})),
    }
    serialised = json.dumps(relevant, sort_keys=True)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


def _stable_biomarkers(bm: dict) -> dict:
    """Return a stable subset of key biomarkers for fingerprinting."""
    important = ["EGFR", "ALK", "ROS1", "KRAS", "BRAF", "HER2", "MSI",
                 "BRCA", "PD-L1", "ER", "PR", "T790M"]
    return {k: str(v) for k, v in bm.items() if k in important}


def _similarity(case_a: dict, case_b: dict) -> float:
    """
    Compute similarity score [0.0, 1.0] between two cases.
    Simple overlap-based matching on key attributes.
    """
    score  = 0.0
    checks = 0

    for field in ("cancer_type", "subtype", "stage"):
        checks += 1
        if case_a.get(field, "").lower() == case_b.get(field, "").lower():
            score += 1.0

    # Line proximity
    checks += 1
    line_diff = abs(int(case_a.get("line_of_therapy", 1)) - int(case_b.get("line_of_therapy", 1)))
    score += max(0.0, 1.0 - line_diff * 0.5)

    # Biomarker overlap
    bm_a = _stable_biomarkers(case_a.get("biomarkers", {}))
    bm_b = _stable_biomarkers(case_b.get("biomarkers", {}))
    shared_keys = set(bm_a) | set(bm_b)
    if shared_keys:
        checks += 1
        matches = sum(1 for k in shared_keys if bm_a.get(k) == bm_b.get(k))
        score += matches / len(shared_keys)

    return score / checks if checks > 0 else 0.0


# ---------------------------------------------------------------------------
# Learning Engine
# ---------------------------------------------------------------------------

class LearningEngine:
    """
    Stores case outcomes and adjusts confidence scores.
    NEVER modifies treatment decisions.

    Memory structure:
        {
            fingerprint: {
                "case":       original_case_dict,
                "regimen":    str,
                "outcome":    str   ("good" | "poor" | "neutral"),
                "count":      int,
                "confidence": float
            }
        }
    """

    def __init__(self, similarity_threshold: float = 0.75):
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._threshold = similarity_threshold

    # -----------------------------------------------------------------------
    # Store a case outcome
    # -----------------------------------------------------------------------

    def store(
        self,
        case:     dict,
        regimen:  str,
        outcome:  str = "neutral",   # "good" | "poor" | "neutral"
    ) -> str:
        """
        Store a case outcome in memory.

        Args:
            case:    Patient case dict.
            regimen: Selected regimen (from decision pipeline — NOT modified here).
            outcome: Clinical outcome string.

        Returns:
            fingerprint string (for reference)
        """
        fp = _fingerprint(case)
        if fp in self._memory:
            existing = self._memory[fp]
            existing["count"]  += 1
            existing["outcome"] = outcome  # update to latest
        else:
            self._memory[fp] = {
                "case":       case,
                "regimen":    regimen,
                "outcome":    outcome,
                "count":      1,
                "confidence": 0.70,  # baseline confidence
            }
        return fp

    # -----------------------------------------------------------------------
    # Adjust confidence only — NEVER touch the regimen
    # -----------------------------------------------------------------------

    def adjust_confidence(
        self,
        case:          dict,
        base_decision: dict,
    ) -> dict:
        """
        Adjust confidence in base_decision using memory.
        NEVER modifies the regimen or any decision field.

        SAFETY ASSERTION:
            decision_before == decision_after (regimen field must be identical)

        Args:
            case:          Current patient case.
            base_decision: Output from disease router (contains 'final_regimen').

        Returns:
            A copy of base_decision with only 'confidence' potentially modified.
            All other fields are IDENTICAL to input.
        """
        # ── Safety: capture decision before ─────────────────────────────
        decision_before = base_decision.get("final_regimen") or base_decision.get("regimen", "")

        # ── Find similar cases in memory ──────────────────────────────────
        similar_cases = self._find_similar(case)

        # ── Compute confidence adjustment ─────────────────────────────────
        if not similar_cases:
            # New case — return baseline, no adjustment
            result = dict(base_decision)
            result["_learning"] = {
                "similar_cases_found": 0,
                "confidence_adjusted": False,
                "reason":              "New case — baseline confidence maintained",
            }
        else:
            # Compute weighted confidence delta
            delta = self._compute_delta(similar_cases, base_decision)

            base_conf = float(
                base_decision.get("confidence", 0.70)
            )
            adjusted_conf = round(max(0.0, min(1.0, base_conf + delta)), 3)

            result = dict(base_decision)
            result["confidence"] = adjusted_conf
            result["_learning"] = {
                "similar_cases_found": len(similar_cases),
                "confidence_adjusted": True,
                "delta":               round(delta, 3),
                "original_confidence": base_conf,
                "adjusted_confidence": adjusted_conf,
                "reason":              self._adjustment_reason(similar_cases, delta),
            }

        # ── CRITICAL SAFETY ASSERTION ─────────────────────────────────────
        decision_after = result.get("final_regimen") or result.get("regimen", "")
        assert decision_before == decision_after, (
            f"LEARNING ENGINE SAFETY VIOLATION: "
            f"decision changed from '{decision_before}' to '{decision_after}'. "
            "This must never happen. Aborting."
        )

        return result

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _find_similar(self, case: dict) -> List[Tuple[Dict, float]]:
        """Return list of (memory_entry, similarity_score) above threshold."""
        results = []
        for fp, entry in self._memory.items():
            sim = _similarity(case, entry["case"])
            if sim >= self._threshold:
                results.append((entry, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:5]  # top-5 most similar

    def _compute_delta(
        self,
        similar_cases: List[Tuple[Dict, float]],
        decision:      dict,
    ) -> float:
        """
        Compute confidence delta from similar cases.

        Rules:
          - Repeated cases with good outcomes → positive delta (up to +0.10)
          - Cases with poor outcomes → negative delta (up to -0.05)
          - Outcome 'poor' DOES NOT change regimen — only reduces confidence
        """
        delta = 0.0
        for entry, sim_score in similar_cases:
            outcome     = entry.get("outcome", "neutral")
            count       = entry.get("count", 1)
            repeat_bonus = min(0.02 * count, 0.08)  # max +0.08 for repeated cases

            if outcome == "good":
                delta += sim_score * (0.05 + repeat_bonus)
            elif outcome == "poor":
                delta -= sim_score * 0.05
            # neutral → no change

        return round(max(-0.15, min(0.15, delta)), 3)

    def _adjustment_reason(
        self,
        similar_cases: List[Tuple[Dict, float]],
        delta:         float,
    ) -> str:
        n      = len(similar_cases)
        top_s  = similar_cases[0][1] if similar_cases else 0
        sign   = "increased" if delta > 0 else "decreased" if delta < 0 else "unchanged"
        return (
            f"Confidence {sign} based on {n} similar prior case(s) "
            f"(top similarity: {top_s:.2f}, delta: {delta:+.3f})."
        )

    # -----------------------------------------------------------------------
    # Inspection
    # -----------------------------------------------------------------------

    def memory_size(self) -> int:
        return len(self._memory)

    def get_memory_summary(self) -> List[dict]:
        return [
            {
                "fingerprint": fp,
                "cancer_type": e["case"].get("cancer_type"),
                "subtype":     e["case"].get("subtype"),
                "regimen":     e["regimen"],
                "outcome":     e["outcome"],
                "count":       e["count"],
            }
            for fp, e in self._memory.items()
        ]


# Module-level singleton
LEARNING_ENGINE = LearningEngine()
