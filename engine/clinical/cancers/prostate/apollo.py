"""
clinical/cancers/prostate/apollo.py — Prostate Cancer Apollo Mode (Phase 7A)

ISOLATED: No imports from lung, breast, or colorectal modules.

Priority:
  1. Metastatic hormone-sensitive (mHSPC) → ADT + intensification
  2. CRPC (castration-resistant) → Abiraterone or Enzalutamide
  3. mCRPC post-AR inhibitor → Docetaxel or PARP inhibitor (BRCA)

Research use only. Not a licensed medical device.
"""
from __future__ import annotations
from typing import Any, Dict


class ProstateApollo:

    def decide(self, case: dict) -> Dict[str, Any]:
        subtype    = case.get("subtype", "")
        line       = case.get("line_of_therapy", 1)
        biomarkers = case.get("biomarkers", {})
        brca       = biomarkers.get("BRCA", "")
        volume     = case.get("disease_volume", "high")  # high/low

        # ── Priority 1: Metastatic hormone-sensitive ─────────────────────
        if subtype == "hormone_sensitive" or "sensitive" in subtype:
            if volume == "high" or True:  # intensification is standard
                regimen    = "ADT + Abiraterone + Prednisone"
                reason     = (
                    "Metastatic hormone-sensitive prostate cancer (mHSPC). "
                    "LATITUDE trial: ADT + abiraterone improved mOS by 16.8 m. "
                    "Intensified ADT is standard of care. NCCN Category 1."
                )
                confidence = 0.92
                priority   = "mHSPC_ADT_intensified"
            return {"regimen": regimen, "confidence": confidence, "reason": reason,
                    "priority": priority, "source": "prostate_apollo"}

        # ── Priority 2: CRPC ─────────────────────────────────────────────
        if "CRPC" in subtype:
            if line == 1:
                regimen    = "Enzalutamide"
                reason     = (
                    "Castration-resistant prostate cancer (CRPC), first AR-inhibitor. "
                    "PREVAIL: enzalutamide improved radiographic PFS and OS. "
                    "NCCN Category 1."
                )
                confidence = 0.90
                priority   = "CRPC_AR_inhibitor_1L"
            elif brca in ("mutant", "positive", "pathogenic"):
                regimen    = "Olaparib"
                reason     = (
                    "mCRPC with BRCA1/2 mutation. PROfound trial: olaparib ORR 33%. "
                    "PARP inhibitor indicated for HRR gene-altered mCRPC. NCCN Category 1."
                )
                confidence = 0.91
                priority   = "mCRPC_PARP_BRCA"
            else:
                regimen    = "Docetaxel + Prednisone"
                reason     = (
                    "mCRPC after AR-inhibitor progression. Docetaxel improves OS "
                    "in mCRPC (TAX327 trial). NCCN Category 1."
                )
                confidence = 0.85
                priority   = "mCRPC_docetaxel"
            return {"regimen": regimen, "confidence": confidence, "reason": reason,
                    "priority": priority, "source": "prostate_apollo"}

        # ── Fallback ─────────────────────────────────────────────────────
        return {
            "regimen":    "ADT (Leuprolide or Degarelix)",
            "confidence": 0.80,
            "reason":     "Androgen deprivation therapy — backbone of prostate cancer treatment.",
            "priority":   "ADT_default",
            "source":     "prostate_apollo",
        }
