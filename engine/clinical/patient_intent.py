"""
clinical/patient_intent.py — Patient Intent Engine (Phase 9, Step 3)

Position in pipeline:
    Guardrail (Step 1)
        → determine_intent()          ← injects case["intent"] into p6a
        → Decision Engine (Apollo / Manhattan / Hybrid)
        → apply_intent_modulation()   ← modifies decision_output after hybrid
        → Quant Layer (Step 2)

What this layer does:
    Converts patient context (goal, frailty, ECOG, age, social support)
    into a treatment intent that modulates how aggressive the recommendation
    should be. The decision engine selects the best guideline-compliant
    option; the intent engine answers "how hard should we push it for
    THIS patient?".

Intent levels:
    aggressive     — curative intent, patient stated, good functional status
    balanced       — standard of care; neither pushing nor pulling back
    de-escalation  — frailty/performance status warrants reduced intensity
    palliative     — comfort-focused; patient preference or poor reserve

Key design rule:
    ECOG is already used by the Phase 6A constraint engine to gate options.
    The intent engine does NOT re-penalise ECOG — it only uses it to confirm
    or adjust the intent level, never to block.

    Intent runs BEFORE the decision engine so it can inject case["intent"]
    into the patient context. Intent modulation runs AFTER, once a regimen
    is selected.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent level constants
# ---------------------------------------------------------------------------

INTENT_AGGRESSIVE    = "aggressive"
INTENT_BALANCED      = "balanced"
INTENT_DE_ESCALATION = "de-escalation"
INTENT_PALLIATIVE    = "palliative"

# Modulation strings — what the intent means for treatment behaviour
_MODULATION = {
    INTENT_AGGRESSIVE:    "Maximise disease control — higher-intensity therapy appropriate given patient's goals and reserve",
    INTENT_BALANCED:      "Balance efficacy with tolerability — standard-of-care intensity",
    INTENT_DE_ESCALATION: "Reduce treatment intensity — functional reserve or frailty warrants de-escalation",
    INTENT_PALLIATIVE:    "Shift toward symptom control and quality of life — minimal-toxicity regimen preferred",
}

# Confidence labels
CONFIDENCE_HIGH     = "high"
CONFIDENCE_MODERATE = "moderate"
CONFIDENCE_LOW      = "low"


# ---------------------------------------------------------------------------
# PatientIntentEngine
# ---------------------------------------------------------------------------

class PatientIntentEngine:
    """
    Phase 9 intent engine.

    Two-step usage in pipeline:
        1. intent_data = engine.determine_intent(patient)
           case["intent"] = intent_data["intent"]      # inject before decision
        2. decision_output = engine.apply_intent_modulation(decision_output, intent_data)
    """

    def determine_intent(self, patient: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine treatment intent from patient context.

        Priority order (highest overrides lower):
            1. Patient-stated goal (treatment_goal field)
            2. Frailty score >= 7  or  ECOG >= 3  → de-escalation
            3. ECOG == 2           → pull toward balanced (not de-escalation alone)
            4. Age > 75 moderates aggressive intent
            5. Social support "poor" → adds feasibility concern to reasoning

        Args:
            patient: Raw patient dict. Reads:
                treatment_goal   : "curative" | "prolong_life" | "comfort"
                frailty_score    : int  (0–9)
                ecog             : int  (0–4)
                age              : int
                social_support   : "good" | "adequate" | "poor"

        Returns:
            {
                "intent":     str,   — one of the 4 intent constants
                "confidence": str,   — high | moderate | low
                "reasoning":  [str], — ordered list of factors that shaped intent
            }
        """
        age     = patient.get("age")
        ecog    = patient.get("ecog")
        frailty = patient.get("frailty_score", 0) or 0
        goal    = (patient.get("treatment_goal") or "").lower().strip()
        social  = (patient.get("social_support") or "adequate").lower().strip()

        intent     = INTENT_BALANCED
        confidence = CONFIDENCE_MODERATE
        reasoning: List[str] = []

        # ── 1. Patient-stated goal — highest priority ─────────────────────
        if goal == "comfort":
            intent     = INTENT_PALLIATIVE
            confidence = CONFIDENCE_HIGH
            reasoning.append("Patient preference: comfort-focused care (treatment_goal=comfort)")

        elif goal == "curative":
            intent = INTENT_AGGRESSIVE
            reasoning.append("Patient preference: curative intent (treatment_goal=curative)")
            # Curative intent still subject to frailty override below

        elif goal in ("prolong_life", "prolong life", "life-prolonging"):
            intent = INTENT_BALANCED
            reasoning.append("Patient preference: life-prolonging therapy (treatment_goal=prolong_life)")

        # ── 2. Hard frailty / performance triggers ────────────────────────
        # These override even a stated curative goal — biology overrides
        # intent when reserve is critically low
        if ecog is not None and ecog >= 3:
            if intent != INTENT_PALLIATIVE:
                intent     = INTENT_DE_ESCALATION
                confidence = CONFIDENCE_HIGH
                reasoning.append(
                    f"ECOG {ecog}: poor performance status — aggressive therapy "
                    "unlikely to be tolerated (used for intent, not as a gate)"
                )

        if frailty >= 7:
            if intent not in (INTENT_PALLIATIVE, INTENT_DE_ESCALATION):
                intent     = INTENT_DE_ESCALATION
                confidence = CONFIDENCE_HIGH
            reasoning.append(
                f"Frailty score {frailty}/9 — significant frailty warrants de-escalation"
            )

        # ── 3. ECOG 2 — moderate pull toward balanced ─────────────────────
        if ecog == 2 and intent == INTENT_AGGRESSIVE:
            intent = INTENT_BALANCED
            reasoning.append(
                f"ECOG {ecog}: moderate performance status moderates aggressive intent"
            )
        elif ecog == 2 and intent == INTENT_BALANCED:
            reasoning.append(
                f"ECOG {ecog}: moderate performance status — balanced approach confirmed"
            )

        # ── 4. Age modifier (softens aggressive, never triggers de-escalation
        #       alone — age alone is not sufficient) ─────────────────────────
        if age is not None and age > 75 and intent == INTENT_AGGRESSIVE:
            intent = INTENT_BALANCED
            reasoning.append(
                f"Age {age}: advanced age moderates aggressive intent "
                "(biology, not a blanket exclusion)"
            )

        # ── 5. Social support — adds to reasoning, doesn't change intent ──
        if social == "poor":
            reasoning.append(
                "Limited social support — treatment feasibility and adherence concern. "
                "Consider simplified regimen and community support services."
            )
            # Downgrade confidence if not already high
            if confidence == CONFIDENCE_MODERATE:
                confidence = CONFIDENCE_LOW

        # Default reasoning when nothing else fired
        if not reasoning:
            reasoning.append(
                "No strong modifiers present — default balanced approach"
            )

        logger.info(
            "PatientIntentEngine: intent=%s confidence=%s factors=%d",
            intent, confidence, len(reasoning)
        )

        return {
            "intent":     intent,
            "confidence": confidence,
            "reasoning":  reasoning,
        }

    def apply_intent_modulation(
        self,
        decision_output: Dict[str, Any],
        intent_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Attach intent context and modulation string to decision output.

        Does NOT change the selected regimen — that is the decision engine's
        job. This layer adds:
            decision_output["treatment_intent"]  — full intent_data dict
            decision_output["modulation"]        — human-readable behaviour note

        Args:
            decision_output: dict from hybrid engine (or _format_output caller)
            intent_data:     output of determine_intent()

        Returns:
            decision_output with intent fields attached (mutates a copy)
        """
        out    = dict(decision_output)
        intent = intent_data.get("intent", INTENT_BALANCED)

        out["treatment_intent"] = intent_data
        out["modulation"]       = _MODULATION.get(intent, _MODULATION[INTENT_BALANCED])
        return out


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

INTENT_ENGINE = PatientIntentEngine()
