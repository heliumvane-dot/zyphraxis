"""
clinical/cancers/breast/apollo.py — Breast Cancer Apollo Mode (Phase 7A)

Fast, instinct-driven single-choice selection for breast cancer.
ISOLATED: No imports from lung, colorectal, or prostate modules.

Priority order:
  1. HER2+ → Trastuzumab-based therapy
  2. ER+   → Endocrine therapy ± CDK4/6 inhibitor
  3. TNBC  → Chemotherapy ± IO (PD-L1 dependent)

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict


class BreastApollo:
    """Fast single-choice breast cancer selection engine."""

    def decide(self, case: dict) -> Dict[str, Any]:
        """
        Select ONE best regimen for a breast cancer case.

        Args:
            case: Validated breast cancer case dict.

        Returns:
            {
                "regimen":    str,
                "confidence": float,
                "reason":     str,
                "priority":   str,
                "source":     "breast_apollo"
            }
        """
        subtype    = case.get("subtype", "")
        stage      = case.get("stage", "IV")
        line       = case.get("line_of_therapy", 1)
        biomarkers = case.get("biomarkers", {})
        pdl1       = float(biomarkers.get("PD-L1", 0) or 0)

        # ── Priority 1: HER2+ → Trastuzumab-based ──────────────────────
        if "HER2+" in subtype:
            if line == 1:
                regimen    = "Trastuzumab + Pertuzumab + Docetaxel"
                reason     = (
                    "HER2+ metastatic breast cancer, first-line. "
                    "CLEOPATRA trial: mOS 57.1 m with dual HER2 blockade. "
                    "NCCN Category 1."
                )
                confidence = 0.93
                priority   = "HER2_targeted_1L"
            else:
                regimen    = "T-DM1 (Ado-Trastuzumab Emtansine)"
                reason     = (
                    "HER2+ mBC, second-line after trastuzumab-based therapy. "
                    "EMILIA trial: improved OS vs lapatinib + capecitabine. "
                    "NCCN Category 1."
                )
                confidence = 0.90
                priority   = "HER2_targeted_2L"

        # ── Priority 2: ER+ → Endocrine therapy ────────────────────────
        elif "ER+" in subtype:
            if line == 1:
                regimen    = "Letrozole + Palbociclib"
                reason     = (
                    "ER+/HER2- metastatic breast cancer, first-line. "
                    "PALOMA-2: mPFS 24.8 m vs letrozole alone (13.8 m). "
                    "CDK4/6 inhibitor + AI is standard of care. NCCN Category 1."
                )
                confidence = 0.91
                priority   = "ER_endocrine_CDK46_1L"
            else:
                regimen    = "Fulvestrant + Abemaciclib"
                reason     = (
                    "ER+/HER2- mBC, progressed on prior endocrine therapy. "
                    "MONARCH-2: mPFS 16.4 m. CDK4/6 inhibitor + fulvestrant. "
                    "NCCN Category 1."
                )
                confidence = 0.88
                priority   = "ER_endocrine_CDK46_2L"

        # ── Priority 3: TNBC → Chemo ± IO ──────────────────────────────
        elif subtype == "TNBC":
            if pdl1 >= 1 and line == 1:
                regimen    = "Pembrolizumab + Nab-Paclitaxel"
                reason     = (
                    "TNBC, PD-L1 CPS ≥ 1, first-line metastatic. "
                    "KEYNOTE-355: mPFS 9.7 m in PD-L1 CPS ≥10 subgroup. "
                    "IO + chemo combination. NCCN Category 1."
                )
                confidence = 0.87
                priority   = "TNBC_IO_chemo_1L"
            else:
                regimen    = "Nab-Paclitaxel"
                reason     = (
                    "TNBC, standard chemotherapy. "
                    "Nab-paclitaxel preferred over solvent-based paclitaxel "
                    "for response rate and tolerability. NCCN Category 1."
                )
                confidence = 0.80
                priority   = "TNBC_chemo"
        else:
            regimen    = "Clinical trial enrollment recommended"
            reason     = f"Subtype '{subtype}' does not match standard pathway. Multidisciplinary review required."
            confidence = 0.50
            priority   = "unknown_subtype"

        return {
            "regimen":    regimen,
            "confidence": confidence,
            "reason":     reason,
            "priority":   priority,
            "source":     "breast_apollo",
        }
