"""
clinical/cancers/colorectal/apollo.py — Colorectal Cancer Apollo Mode (Phase 7A)

ISOLATED: No imports from lung, breast, or prostate modules.

CRITICAL RULE: KRAS/NRAS mutant → NO anti-EGFR therapy (cetuximab/panitumumab).

Priority:
  1. MSI-H → IO (pembrolizumab)
  2. BRAF V600E → FOLFOX + bevacizumab or BRAF-targeted
  3. RAS wildtype → FOLFOX + cetuximab (anti-EGFR eligible)
  4. KRAS/NRAS mutant → FOLFOX + bevacizumab (NO anti-EGFR)

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict


class ColorectalApollo:

    def decide(self, case: dict) -> Dict[str, Any]:
        subtype    = case.get("subtype", "")
        line       = case.get("line_of_therapy", 1)
        biomarkers = case.get("biomarkers", {})
        location   = case.get("tumor_location", "left")  # left/right sidedness

        # ── Priority 1: MSI-H → IO ──────────────────────────────────────
        if subtype == "MSI-H" or biomarkers.get("MSI") == "high":
            if line == 1:
                regimen    = "Pembrolizumab"
                reason     = (
                    "MSI-H/dMMR mCRC, first-line. KEYNOTE-177: mPFS 16.5 m vs 8.2 m "
                    "with chemotherapy. IO first-line is now standard. NCCN Category 1."
                )
                confidence = 0.93
            else:
                regimen    = "Nivolumab + Ipilimumab"
                reason     = (
                    "MSI-H/dMMR mCRC, second-line. CheckMate-142 ORR 55%. "
                    "Dual IO combination. NCCN Category 1."
                )
                confidence = 0.88
            return {"regimen": regimen, "confidence": confidence, "reason": reason,
                    "priority": "MSI_H_IO", "source": "colorectal_apollo"}

        # ── Priority 2: BRAF V600E ──────────────────────────────────────
        if subtype == "BRAF_V600E" or biomarkers.get("BRAF") == "V600E":
            if line == 1:
                regimen    = "FOLFOXIRI + Bevacizumab"
                reason     = (
                    "BRAF V600E mCRC, first-line. TRIBE2 trial supports intensified "
                    "FOLFOXIRI + bevacizumab for fit patients. NCCN Category 2A."
                )
                confidence = 0.82
            else:
                regimen    = "Encorafenib + Cetuximab"
                reason     = (
                    "BRAF V600E mCRC, second-line. BEACON-CRC: ORR 26.8% vs 2% standard. "
                    "NCCN Category 1 for BRAF V600E after prior therapy."
                )
                confidence = 0.90
            return {"regimen": regimen, "confidence": confidence, "reason": reason,
                    "priority": "BRAF_targeted", "source": "colorectal_apollo"}

        # ── Priority 3: KRAS/NRAS mutant → NO anti-EGFR ─────────────────
        if subtype in ("KRAS_mut", "NRAS_mut") or biomarkers.get("KRAS") == "mutant":
            regimen    = "FOLFOX + Bevacizumab"
            reason     = (
                "KRAS/NRAS mutant mCRC — anti-EGFR therapy (cetuximab/panitumumab) "
                "is CONTRAINDICATED: RAS mutations predict resistance and potential harm. "
                "FOLFOX + bevacizumab is standard. NCCN Category 1."
            )
            confidence = 0.92
            return {"regimen": regimen, "confidence": confidence, "reason": reason,
                    "priority": "RAS_mutant_no_antiEGFR", "source": "colorectal_apollo"}

        # ── Priority 4: RAS wildtype → anti-EGFR eligible ───────────────
        if subtype == "RAS_wt":
            if location == "left":
                regimen    = "FOLFOX + Cetuximab"
                reason     = (
                    "RAS wildtype, left-sided mCRC. Anti-EGFR + FOLFOX: superior OS "
                    "for left-sided RAS-wt. FIRE-3, CALGB 80405. NCCN Category 1."
                )
                confidence = 0.91
            else:
                regimen    = "FOLFOX + Bevacizumab"
                reason     = (
                    "RAS wildtype, right-sided mCRC. Anti-EGFR less effective right-sided; "
                    "bevacizumab + FOLFOX preferred. NCCN Category 1."
                )
                confidence = 0.88
            return {"regimen": regimen, "confidence": confidence, "reason": reason,
                    "priority": "RAS_wt_antiEGFR_eligible", "source": "colorectal_apollo"}

        # ── Fallback ─────────────────────────────────────────────────────
        return {
            "regimen":    "FOLFOX + Bevacizumab",
            "confidence": 0.75,
            "reason":     "Standard doublet + bevacizumab; biomarker status requires clarification.",
            "priority":   "default",
            "source":     "colorectal_apollo",
        }
