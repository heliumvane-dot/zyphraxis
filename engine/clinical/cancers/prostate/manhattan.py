"""
clinical/cancers/prostate/manhattan.py — Prostate Manhattan Mode (Phase 7A)
ISOLATED. Research use only.
"""
from __future__ import annotations
from typing import Any, Dict


class ProstateManhattan:
    def evaluate(self, case: dict) -> Dict[str, Any]:
        from clinical.cancers.prostate.apollo import ProstateApollo
        result = ProstateApollo().decide(case)
        result["source"] = "prostate_manhattan"
        result["score"]  = int(result["confidence"] * 100)
        result["reason"] = f"Manhattan evaluation (prostate): {result['reason']}"
        return result
