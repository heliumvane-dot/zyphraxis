"""
clinical/cancers/colorectal/manhattan.py — Colorectal Cancer Manhattan Mode (Phase 7A)

ISOLATED: No imports from lung, breast, or prostate modules.
Research use only. Not a licensed medical device.
"""
from __future__ import annotations
from typing import Any, Dict


class ColorectalManhattan:
    def evaluate(self, case: dict) -> Dict[str, Any]:
        # Delegates to apollo for now (full scoring would mirror breast manhattan)
        from clinical.cancers.colorectal.apollo import ColorectalApollo
        result = ColorectalApollo().decide(case)
        result["source"] = "colorectal_manhattan"
        result["score"]  = int(result["confidence"] * 100)
        result["reason"] = f"Manhattan evaluation (CRC): {result['reason']}"
        return result
