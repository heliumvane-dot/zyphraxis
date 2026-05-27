"""
clinical/cancers/breast/manhattan.py — Breast Cancer Manhattan Mode (Phase 7A)

Deep, structured evaluation of ALL breast cancer options.
ISOLATED: No imports from lung, colorectal, or prostate modules.

Evaluates all candidates and returns the top-ranked regimen.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Breast cancer treatment catalogue (internal to this module)
# ---------------------------------------------------------------------------

_BREAST_CATALOGUE: List[Dict[str, Any]] = [
    # HER2+ options
    {
        "regimen":        "Trastuzumab + Pertuzumab + Docetaxel",
        "subtype":        "HER2+",
        "line":           1,
        "evidence":       "CLEOPATRA (NEJM 2012)",
        "evidence_level": "1A",
        "trial_orr":      0.80,
        "modality":       "targeted+chemo",
    },
    {
        "regimen":        "T-DM1 (Ado-Trastuzumab Emtansine)",
        "subtype":        "HER2+",
        "line":           2,
        "evidence":       "EMILIA (NEJM 2012)",
        "evidence_level": "1A",
        "trial_orr":      0.44,
        "modality":       "antibody_drug_conjugate",
    },
    {
        "regimen":        "T-DXd (Trastuzumab Deruxtecan)",
        "subtype":        "HER2+",
        "line":           3,
        "evidence":       "DESTINY-Breast03 (NEJM 2022)",
        "evidence_level": "1A",
        "trial_orr":      0.79,
        "modality":       "antibody_drug_conjugate",
    },
    # ER+ options
    {
        "regimen":        "Letrozole + Palbociclib",
        "subtype":        "ER+",
        "line":           1,
        "evidence":       "PALOMA-2 (NEJM 2016)",
        "evidence_level": "1A",
        "trial_orr":      0.55,
        "modality":       "endocrine+CDK4/6",
    },
    {
        "regimen":        "Fulvestrant + Abemaciclib",
        "subtype":        "ER+",
        "line":           2,
        "evidence":       "MONARCH-2 (JCO 2017)",
        "evidence_level": "1A",
        "trial_orr":      0.35,
        "modality":       "endocrine+CDK4/6",
    },
    {
        "regimen":        "Everolimus + Exemestane",
        "subtype":        "ER+",
        "line":           2,
        "evidence":       "BOLERO-2 (NEJM 2012)",
        "evidence_level": "1A",
        "trial_orr":      0.12,
        "modality":       "endocrine+mTOR",
    },
    # TNBC options
    {
        "regimen":        "Pembrolizumab + Nab-Paclitaxel",
        "subtype":        "TNBC",
        "line":           1,
        "evidence":       "KEYNOTE-355 (Lancet 2022)",
        "evidence_level": "1A",
        "trial_orr":      0.53,
        "modality":       "IO+chemo",
        "pdl1_required":  True,
    },
    {
        "regimen":        "Nab-Paclitaxel",
        "subtype":        "TNBC",
        "line":           1,
        "evidence":       "NCCN TNBC Guidelines",
        "evidence_level": "1B",
        "trial_orr":      0.33,
        "modality":       "chemo",
    },
    {
        "regimen":        "Sacituzumab Govitecan",
        "subtype":        "TNBC",
        "line":           2,
        "evidence":       "ASCENT (NEJM 2021)",
        "evidence_level": "1A",
        "trial_orr":      0.35,
        "modality":       "antibody_drug_conjugate",
    },
]

_EVIDENCE_RANK = {"1A": 4, "1B": 3, "2A": 2, "2B": 1}


class BreastManhattan:
    """Deep evaluation engine — scores all breast cancer candidates."""

    def evaluate(self, case: dict) -> Dict[str, Any]:
        """
        Evaluate all breast cancer candidates for a case.

        Returns the top-ranked regimen dict.
        """
        subtype = case.get("subtype", "")
        line    = case.get("line_of_therapy", 1)
        bm      = case.get("biomarkers", {})
        pdl1    = float(bm.get("PD-L1", 0) or 0)

        scored = []
        for candidate in _BREAST_CATALOGUE:
            # Only consider matching subtype options
            cand_subtype = candidate["subtype"]
            if not (cand_subtype == subtype or cand_subtype in subtype):
                continue

            score = 0
            reasons = []

            # Line match
            if candidate["line"] == line:
                score += 50
                reasons.append("line_match")
            elif candidate["line"] < line:
                score += 10  # lower-line options considered at lower priority
                reasons.append("prior_line_option")

            # Evidence level
            ev = _EVIDENCE_RANK.get(candidate.get("evidence_level", ""), 0)
            score += ev * 10
            if ev >= 3:
                reasons.append("high_evidence")

            # PD-L1 gating for IO
            if candidate.get("pdl1_required") and pdl1 < 1:
                score -= 100
                reasons.append("pdl1_insufficient")
            elif candidate.get("pdl1_required") and pdl1 >= 10:
                score += 20
                reasons.append("pdl1_high")

            # Trial ORR
            score += int(candidate.get("trial_orr", 0) * 30)

            scored.append({
                "regimen":    candidate["regimen"],
                "score":      score,
                "reasons":    reasons,
                "evidence":   candidate.get("evidence", ""),
                "confidence": min(0.95, 0.60 + score / 200),
            })

        if not scored:
            return {
                "regimen":    "Clinical trial enrollment recommended",
                "score":      0,
                "reasons":    ["no_matching_candidate"],
                "evidence":   "",
                "confidence": 0.50,
            }

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[0]
        top["reason"] = (
            f"Manhattan evaluation: {top['regimen']} scored highest "
            f"({top['score']} pts). Reasons: {', '.join(top['reasons'])}."
        )
        return top
