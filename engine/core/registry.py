"""
core/registry.py — Zyphraxis Phase 7A: Cancer Module Registry

Maps cancer_type strings to their pipeline runner functions.
Hard failure on unknown types — no silent fallback.

ISOLATION RULE: Each cancer imports only its own module.
Cross-cancer imports are FORBIDDEN.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Callable, Dict


def _run_lung(case: dict) -> dict:
    """Route lung/NSCLC to Phase 6 pipeline — UNTOUCHED."""
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from pipeline_integration import run_phase6
    text = run_phase6(case)
    return {
        "cancer_type": "lung",
        "output_text": text,
        "pipeline": "phase6_nsclc",
    }


def _run_breast(case: dict) -> dict:
    """Route breast cancer to breast-specific pipeline."""
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from clinical.cancers.breast.apollo import BreastApollo
    from clinical.cancers.breast.manhattan import BreastManhattan
    from clinical.cancers.breast.schema import validate_breast_case

    validate_breast_case(case)
    apollo     = BreastApollo()
    manhattan  = BreastManhattan()
    a_out      = apollo.decide(case)
    m_out      = manhattan.evaluate(case)
    # Hybrid: prefer apollo where both agree, else highest-confidence
    final      = a_out if a_out["regimen"] == m_out["regimen"] else a_out
    return {
        "cancer_type":    "breast",
        "final_regimen":  final["regimen"],
        "line":           case.get("line_of_therapy", 1),
        "confidence":     final["confidence"],
        "reason":         final["reason"],
        "apollo":         a_out,
        "manhattan":      m_out,
        "pipeline":       "phase7a_breast",
    }


def _run_colorectal(case: dict) -> dict:
    """Route colorectal cancer to colorectal-specific pipeline."""
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from clinical.cancers.colorectal.apollo import ColorectalApollo
    from clinical.cancers.colorectal.manhattan import ColorectalManhattan
    from clinical.cancers.colorectal.schema import validate_colorectal_case

    validate_colorectal_case(case)
    apollo    = ColorectalApollo()
    manhattan = ColorectalManhattan()
    a_out     = apollo.decide(case)
    m_out     = manhattan.evaluate(case)
    final     = a_out if a_out["regimen"] == m_out["regimen"] else a_out
    return {
        "cancer_type":    "colorectal",
        "final_regimen":  final["regimen"],
        "line":           case.get("line_of_therapy", 1),
        "confidence":     final["confidence"],
        "reason":         final["reason"],
        "apollo":         a_out,
        "manhattan":      m_out,
        "pipeline":       "phase7a_colorectal",
    }


def _run_prostate(case: dict) -> dict:
    """Route prostate cancer to prostate-specific pipeline."""
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from clinical.cancers.prostate.apollo import ProstateApollo
    from clinical.cancers.prostate.manhattan import ProstateManhattan
    from clinical.cancers.prostate.schema import validate_prostate_case

    validate_prostate_case(case)
    apollo    = ProstateApollo()
    manhattan = ProstateManhattan()
    a_out     = apollo.decide(case)
    m_out     = manhattan.evaluate(case)
    final     = a_out if a_out["regimen"] == m_out["regimen"] else a_out
    return {
        "cancer_type":    "prostate",
        "final_regimen":  final["regimen"],
        "line":           case.get("line_of_therapy", 1),
        "confidence":     final["confidence"],
        "reason":         final["reason"],
        "apollo":         a_out,
        "manhattan":      m_out,
        "pipeline":       "phase7a_prostate",
    }


# ---------------------------------------------------------------------------
# Registry — the single source of truth for supported cancers
# ---------------------------------------------------------------------------

CANCER_REGISTRY: Dict[str, Callable[[dict], dict]] = {
    "lung":       _run_lung,
    "breast":     _run_breast,
    "colorectal": _run_colorectal,
    "prostate":   _run_prostate,
}
