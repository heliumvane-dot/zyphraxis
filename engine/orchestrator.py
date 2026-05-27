"""
orchestrator.py — Zyphraxis Phase 7 Orchestrator

Central entry point for Phase 7 (7A + 7B + 7C).

Modes:
  run_7a(case)                    → Multi-cancer single-step decision
  run_7b(case, progressions)      → Timeline simulation
  run_7c(case, store_outcome)     → Decision + learning confidence adjustment

Phase 6 NSCLC pipeline is UNTOUCHED — routed through disease_router → registry.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from router.disease_router    import DISEASE_ROUTER
from timeline.timeline_engine import TIMELINE_ENGINE
from learning.learning_engine import LEARNING_ENGINE
from typing import Any, Dict, List, Optional


VERSION = "7.0.0"

CDSS_DISCLAIMER = (
    "This output was produced by a Clinical Decision Support System (CDSS). "
    "It must be reviewed by a licensed oncologist before any clinical action. "
    "Research use only. Not a licensed medical device."
)


# ---------------------------------------------------------------------------
# Phase 7A — Multi-cancer single-step decision
# ---------------------------------------------------------------------------

def run_7a(case: dict) -> Dict[str, Any]:
    """
    Phase 7A: Route case to correct cancer pipeline and return decision.

    Args:
        case: Must contain 'cancer_type'. For non-NSCLC cancers must also
              contain 'subtype', 'stage', 'line_of_therapy'.

    Returns:
        Decision dict with cancer_type, final_regimen, confidence, reason.
    """
    return DISEASE_ROUTER.route(case)


# ---------------------------------------------------------------------------
# Phase 7B — Timeline simulation
# ---------------------------------------------------------------------------

def run_7b(
    case:               dict,
    progression_states: Optional[List[dict]] = None,
    max_steps:          int = 4,
) -> Dict[str, Any]:
    """
    Phase 7B: Simulate sequential therapy lines over time.

    Args:
        case:               Initial patient case.
        progression_states: List of state update dicts to apply at each
                           progression event.
        max_steps:          Maximum steps to simulate.

    Returns:
        Timeline simulation result with steps, total_lines, final_state.
    """
    return TIMELINE_ENGINE.simulate(
        initial_case       = case,
        progression_states = progression_states,
        max_steps          = max_steps,
    )


# ---------------------------------------------------------------------------
# Phase 7C — Learning + confidence adjustment
# ---------------------------------------------------------------------------

def run_7c(
    case:          dict,
    store_outcome: Optional[str] = None,   # "good" | "poor" | "neutral" | None
) -> Dict[str, Any]:
    """
    Phase 7C: Decision + learning-adjusted confidence.

    SAFETY: The regimen decision is determined FIRST by the decision pipeline,
    then confidence is optionally adjusted by the learning engine.
    The regimen CANNOT change.

    Args:
        case:          Patient case dict.
        store_outcome: If provided, store this case in learning memory.

    Returns:
        Decision dict with confidence potentially adjusted.
        Includes '_learning' metadata.
    """
    # ── Step 1: Get base decision (ISOLATED from learning) ───────────────
    base_decision = DISEASE_ROUTER.route(case)

    # ── Step 2: Adjust confidence only (learning is read-only on decision) ─
    adjusted = LEARNING_ENGINE.adjust_confidence(
        case          = case,
        base_decision = base_decision,
    )

    # ── Step 3: Optionally store outcome ─────────────────────────────────
    if store_outcome:
        regimen = base_decision.get("final_regimen") or base_decision.get("regimen", "")
        LEARNING_ENGINE.store(case, regimen, store_outcome)
        adjusted["_stored"] = True

    return adjusted


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("\n=== Zyphraxis Phase 7 — Self-Test ===\n")

    # Quick smoke test: one case per cancer
    smoke_cases = [
        {"cancer_type": "lung",       "biomarkers": {"EGFR": "positive"}, "line": 1,
         "stage": "IV", "driver_mutation": "EGFR"},
        {"cancer_type": "breast",     "subtype": "HER2+", "stage": "IV", "line_of_therapy": 1,
         "biomarkers": {}},
        {"cancer_type": "colorectal", "subtype": "KRAS_mut", "stage": "IV", "line_of_therapy": 1,
         "biomarkers": {"KRAS": "mutant"}},
        {"cancer_type": "prostate",   "subtype": "hormone_sensitive", "stage": "IV", "line_of_therapy": 1,
         "biomarkers": {}},
    ]

    for case in smoke_cases:
        result = run_7a(case)
        ct = case["cancer_type"]
        if ct == "lung":
            print(f"[LUNG]       → Phase 6 pipeline (NSCLC unchanged)")
        else:
            print(f"[{ct.upper():<12}] → {result.get('final_regimen', '?')} "
                  f"(conf={result.get('confidence', 0):.2f})")

    print("\n=== Smoke test complete ===\n")
    print(CDSS_DISCLAIMER)
