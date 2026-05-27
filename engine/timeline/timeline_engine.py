"""
timeline/timeline_engine.py — Zyphraxis Phase 7B: Sequential Simulation Engine

WRAPPER ONLY. This module:
  ✓ Loops over time steps
  ✓ Calls orchestrator/router for each decision
  ✓ Calls cancer-specific progression.detect() to advance state
  ✓ Increments line_of_therapy on progression

This module MUST NOT:
  ✗ Modify inputs to the decision pipeline
  ✗ Modify decision logic in any engine
  ✗ Touch hybrid_engine.py or policy_engine.py
  ✗ Use confidence for arbitration

RULE: A single-step run through this engine MUST produce output
      identical to Phase 6 / Phase 7A router output.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from router.disease_router import DISEASE_ROUTER


# ---------------------------------------------------------------------------
# Progression module loader
# ---------------------------------------------------------------------------

def _get_progression_module(cancer_type: str):
    """
    Load the progression detection module for a cancer type.
    Returns a module with a detect(state) function.
    """
    ct = cancer_type.lower()
    if ct == "lung":
        from engine.cancers.lung_progression import detect
        return detect
    elif ct == "breast":
        from clinical.cancers.breast.progression import detect
        return detect
    elif ct == "colorectal":
        from clinical.cancers.colorectal.progression import detect
        return detect
    elif ct == "prostate":
        from clinical.cancers.prostate.progression import detect
        return detect
    else:
        raise ValueError(f"TimelineEngine: No progression module for cancer_type='{ct}'")


# ---------------------------------------------------------------------------
# Timeline Engine
# ---------------------------------------------------------------------------

class TimelineEngine:
    """
    Simulates sequential clinical decision-making over time.

    Each step:
      1. Run decision pipeline for current state
      2. Detect progression using cancer-specific progression module
      3. If progressed: increment line_of_therapy, update state
      4. Repeat until max_steps or no progression

    This is a WRAPPER — it does not contain any clinical logic.
    All clinical reasoning is delegated to the cancer-specific pipelines.
    """

    def simulate(
        self,
        initial_case: dict,
        progression_states: Optional[List[dict]] = None,
        max_steps: int = 4,
    ) -> Dict[str, Any]:
        """
        Run a multi-step simulation.

        Args:
            initial_case:       The starting patient case dict.
            progression_states: Optional list of state updates to apply at each
                                progression event (e.g. new resistance mutations).
                                If None or shorter than actual progressions,
                                default state advancement is used.
            max_steps:          Maximum simulation steps (default 4).

        Returns:
            {
                "steps":        List of step results,
                "total_lines":  Number of therapy lines simulated,
                "final_state":  Final patient state dict,
                "cancer_type":  str,
            }
        """
        cancer_type      = initial_case.get("cancer_type", "lung").lower()
        detect_fn        = _get_progression_module(cancer_type)
        progression_states = progression_states or []

        current_state = copy.deepcopy(initial_case)
        steps         = []
        prog_count    = 0

        for step_num in range(1, max_steps + 1):
            # ── Step 1: Run decision pipeline ────────────────────────────
            decision = DISEASE_ROUTER.route(copy.deepcopy(current_state))

            step_record = {
                "step":           step_num,
                "line_of_therapy": current_state.get("line_of_therapy", 1),
                "decision":       decision,
                "state_snapshot": {
                    k: v for k, v in current_state.items()
                    if k not in ("_raw",)
                },
            }

            # ── Step 2: Detect progression ────────────────────────────────
            progressed, prog_reason = detect_fn(current_state)
            step_record["progressed"]        = progressed
            step_record["progression_reason"] = prog_reason

            steps.append(step_record)

            if not progressed:
                # Stable — simulation ends
                break

            # ── Step 3: Advance state on progression ──────────────────────
            prog_count += 1
            current_state = copy.deepcopy(current_state)
            current_state["line_of_therapy"] = current_state.get("line_of_therapy", 1) + 1

            # Apply any externally supplied state update for this progression
            if prog_count <= len(progression_states):
                for k, v in progression_states[prog_count - 1].items():
                    current_state[k] = v

            # Clear progression markers so we don't re-trigger immediately
            current_state.pop("progression_confirmed", None)
            current_state["radiology"] = {}

        return {
            "steps":       steps,
            "total_lines": current_state.get("line_of_therapy", 1),
            "final_state": current_state,
            "cancer_type": cancer_type,
        }


# Module-level singleton
TIMELINE_ENGINE = TimelineEngine()
