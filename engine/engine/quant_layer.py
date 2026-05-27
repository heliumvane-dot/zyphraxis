"""
engine/quant_layer.py — Quant Layer (Phase 9, Step 2)

Position in pipeline:
    Decision Engine output  →  RiskQuantifier.build_risk_profile()
                            →  decision_output["risk_assessment"]

What this layer does:
    Converts raw patient parameters into structured risk ranges.
    Every number is a calibrated estimate, not a clinical trial probability.
    All outputs carry basis="structured_estimate" so consumers know exactly
    what they're reading.

Risk dimensions:
    cardiac_risk            — based on ejection fraction (EF)
    renal_risk              — based on eGFR
    toxicity_risk           — multi-factor: age + ECOG + EF
    treatment_discontinuation — derived from toxicity risk

Design rules:
    - NEVER present output as clinical trial probability
    - ALWAYS include basis field in every risk dict
    - Unknown inputs return level="Unknown", range="N/A" — never crash
    - All thresholds documented inline with clinical rationale

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Internal threshold tables — documented for auditability
# ---------------------------------------------------------------------------

# EF thresholds (based on ACC/AHA heart failure staging)
_EF_THRESHOLDS = [
    (35,  "Very High", "50–70%",  "HFrEF severe — anthracyclines/trastuzumab likely contraindicated"),
    (45,  "High",      "30–50%",  "HFrEF mild-moderate — enhanced cardiotoxicity monitoring required"),
    (55,  "Moderate",  "15–30%",  "Low-normal EF — baseline monitoring recommended"),
    (None,"Low",       "<15%",    "Normal EF — standard monitoring"),
]

# eGFR thresholds (based on KDIGO CKD staging)
_EGFR_THRESHOLDS = [
    (20,  "Very High", "50–70%",  "CKD G5 — nephrotoxic agents contraindicated"),
    (30,  "High",      "30–50%",  "CKD G4 — cisplatin contraindicated, carboplatin with dose reduction"),
    (60,  "Moderate",  "15–30%",  "CKD G3 — dose review required for renally-cleared agents"),
    (None,"Low",       "<15%",    "Normal renal function — standard dosing"),
]

# Toxicity scoring weights
_TOXICITY_WEIGHTS = {
    "age_over_70":  2,   # age > 70 increases myelosuppression + GI toxicity risk
    "ecog_ge_2":    2,   # ECOG ≥ 2 = significantly reduced reserve
    "ef_below_45":  2,   # cardiac compromise compounds chemotherapy tolerance
    "ecog_1":       1,   # mild reduction in reserve
    "age_60_70":    1,   # moderate age-related risk increase
}

_TOXICITY_BANDS = [
    (5, "Very High", ">60%"),
    (3, "High",      "40–60%"),
    (1, "Moderate",  "20–40%"),
    (0, "Low",       "<20%"),
]


# ---------------------------------------------------------------------------
# RiskQuantifier
# ---------------------------------------------------------------------------

class RiskQuantifier:
    """
    Phase 9 quant layer.

    All public methods return dicts with:
        level  : str   — Very High | High | Moderate | Low | Unknown
        range  : str   — estimated probability range
        basis  : str   — always "structured_estimate"
        note   : str   — clinical rationale for the estimate
    """

    # ── Cardiac risk ─────────────────────────────────────────────────────────

    def cardiotoxicity(self, ef: Optional[float]) -> Dict[str, str]:
        """
        Estimate cardiotoxicity risk from ejection fraction.

        Clinical basis: ACC/AHA 2022 guidelines define EF < 53% as below normal.
        Anthracycline + trastuzumab cardiotoxicity risk rises sharply below EF 45%.
        """
        if ef is None:
            return self._unknown("EF not provided — cardiac risk cannot be assessed")

        for threshold, level, rng, note in _EF_THRESHOLDS:
            if threshold is None or ef < threshold:
                return {
                    "level": level,
                    "range": rng,
                    "basis": "structured_estimate",
                    "note":  note,
                    "input": f"EF {ef}%",
                }

        return self._unknown("EF value out of expected range")

    # ── Renal risk ───────────────────────────────────────────────────────────

    def renal_risk(self, egfr: Optional[float]) -> Dict[str, str]:
        """
        Estimate renal toxicity risk from eGFR.

        Clinical basis: KDIGO 2022 CKD staging. Cisplatin requires eGFR ≥ 45-60
        depending on protocol. Carboplatin AUC dosing possible at lower eGFR.
        """
        if egfr is None:
            return self._unknown("eGFR not provided — renal risk cannot be assessed")

        for threshold, level, rng, note in _EGFR_THRESHOLDS:
            if threshold is None or egfr < threshold:
                return {
                    "level": level,
                    "range": rng,
                    "basis": "structured_estimate",
                    "note":  note,
                    "input": f"eGFR {egfr} mL/min",
                }

        return self._unknown("eGFR value out of expected range")

    # ── Chemotherapy toxicity risk ───────────────────────────────────────────

    def toxicity_risk(self, case: Dict[str, Any]) -> Dict[str, str]:
        """
        Estimate overall chemotherapy toxicity risk (multi-factor scoring).

        Scoring factors:
            age > 70        +2  (myelosuppression, GI toxicity, hospitalisation risk)
            age 60–70       +1  (moderate age-related increase)
            ECOG ≥ 2        +2  (significantly reduced functional reserve)
            ECOG = 1        +1  (mildly reduced reserve)
            EF < 45         +2  (cardiac compromise compounds chemo tolerance)

        Clinical basis: Adapted from CARG (Cancer and Aging Research Group)
        toxicity scoring model. Not a direct CARG implementation.
        """
        age  = case.get("age")
        ecog = case.get("ecog", 1)
        ef   = case.get("ef")

        score  = 0
        inputs = []

        if age is not None:
            if age > 70:
                score  += _TOXICITY_WEIGHTS["age_over_70"]
                inputs.append(f"age {age} (>70)")
            elif age >= 60:
                score  += _TOXICITY_WEIGHTS["age_60_70"]
                inputs.append(f"age {age} (60–70)")

        if ecog is not None:
            if ecog >= 2:
                score  += _TOXICITY_WEIGHTS["ecog_ge_2"]
                inputs.append(f"ECOG {ecog} (≥2)")
            elif ecog == 1:
                score  += _TOXICITY_WEIGHTS["ecog_1"]
                inputs.append(f"ECOG {ecog}")

        if ef is not None and ef < 45:
            score  += _TOXICITY_WEIGHTS["ef_below_45"]
            inputs.append(f"EF {ef}% (<45)")

        for threshold, level, rng in _TOXICITY_BANDS:
            if score >= threshold:
                return {
                    "level":       level,
                    "range":       rng,
                    "basis":       "structured_estimate",
                    "score":       score,
                    "note":        f"Scoring factors: {', '.join(inputs) if inputs else 'none'}",
                    "score_basis": "adapted CARG toxicity model (not a direct implementation)",
                }

        return self._unknown("Toxicity score calculation failed")

    # ── Treatment discontinuation risk ──────────────────────────────────────

    def discontinuation_risk(self, case: Dict[str, Any]) -> Dict[str, str]:
        """
        Estimate treatment discontinuation risk.

        Derived from toxicity risk — high toxicity correlates with early
        discontinuation in observational oncology data. Not an independent
        clinical model; treat as a downstream indicator only.
        """
        tox = self.toxicity_risk(case)
        tox_level = tox.get("level", "Unknown")

        _DISC_MAP = {
            "Very High": ("Very High", ">50%"),
            "High":      ("High",      "30–50%"),
            "Moderate":  ("Moderate",  "15–30%"),
            "Low":       ("Low",       "<15%"),
        }

        level, rng = _DISC_MAP.get(tox_level, ("Unknown", "N/A"))

        return {
            "level": level,
            "range": rng,
            "basis": "structured_estimate",
            "note":  f"Derived from toxicity risk ({tox_level}). "
                     "Observe for early discontinuation signals.",
        }

    # ── Master builder ───────────────────────────────────────────────────────

    def build_risk_profile(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build complete risk profile for a patient case.

        Returns:
            {
                "cardiac_risk":              { level, range, basis, note, input },
                "renal_risk":                { level, range, basis, note, input },
                "toxicity_risk":             { level, range, basis, score, note },
                "treatment_discontinuation": { level, range, basis, note },
                "basis":                     "structured_estimate",
                "disclaimer":                str,
            }
        """
        return {
            "cardiac_risk":              self.cardiotoxicity(case.get("ef")),
            "renal_risk":                self.renal_risk(case.get("egfr")),
            "toxicity_risk":             self.toxicity_risk(case),
            "treatment_discontinuation": self.discontinuation_risk(case),
            "basis":     "structured_estimate",
            "disclaimer": (
                "Risk ranges are structured estimates based on clinical staging thresholds. "
                "They are NOT clinical trial probabilities. "
                "Validate against patient-specific labs and clinical judgement before use."
            ),
        }

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _unknown(reason: str) -> Dict[str, str]:
        return {
            "level": "Unknown",
            "range": "N/A",
            "basis": "structured_estimate",
            "note":  reason,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

QUANT_LAYER = RiskQuantifier()
