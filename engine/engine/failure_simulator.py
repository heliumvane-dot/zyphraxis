"""
engine/failure_simulator.py — Failure Simulator (Phase 9, Step 5)

Position in pipeline:
    Guardrail → Uncertainty → Intent → Decision → Intent Modulation
        → Quant Layer
            → simulate()         ← LAST, reads from all previous layers
                → decision_output["failure_simulation"]
                → _format_output()

What this layer does:
    Predicts HOW a treatment plan is likely to fail BEFORE it happens.
    Identifies early warning signs clinicians should monitor.
    Proposes specific exit strategies for each failure mode.

    "Before: here's the plan.
     After:  here's the plan, here's how it might fail,
             and here's how we recover."

Design rules:
    1. Reads from quant layer output (risk_profile) — never re-reads raw
       EF/eGFR directly. Risk scores must stay consistent across layers.
    2. Reads penalty_score from uncertainty to weight failure confidence.
       High uncertainty → label failures as "possible" not "likely".
    3. Reads intent from hybrid_out to catch intent-specific failure modes
       (de-escalation risks suboptimal tumour control; aggressive risks
       organ-system crash).
    4. Deduplicates signals and strategies — no repeated lines in output.
    5. Every failure entry has: mode, confidence, early_signs, exit_strategy.

Failure modes tracked:
    Treatment intolerance        — organ reserve + toxicity risk
    Suboptimal tumour control    — de-escalation intent + disease burden
    Treatment discontinuation    — social barriers + very high toxicity
    Cardiac decompensation       — very high cardiac risk
    Renal failure progression    — very high renal risk
    Uncertainty-driven error     — high penalty score from missing data

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Confidence labels (modulated by uncertainty penalty)
# ---------------------------------------------------------------------------

_CONFIDENCE_LIKELY   = "likely"
_CONFIDENCE_POSSIBLE = "possible"
_CONFIDENCE_WATCH    = "watch"


def _confidence_from_penalty(base: str, penalty_score: int) -> str:
    """
    Downgrade failure confidence when uncertainty is high.

    If the system doesn't have complete data, it can't be certain about
    failure modes either — high uncertainty turns 'likely' into 'possible'.
    """
    if penalty_score >= 60:
        if base == _CONFIDENCE_LIKELY:
            return _CONFIDENCE_POSSIBLE
    return base


# ---------------------------------------------------------------------------
# FailureSimulator
# ---------------------------------------------------------------------------

class FailureSimulator:
    """
    Phase 9 failure simulation engine.

    Usage:
        failure = FAILURE_SIMULATOR.simulate(patient, hybrid_out, risk_profile, uncertainty)
        decision_output["failure_simulation"] = failure
    """

    def simulate(
        self,
        patient:      Dict[str, Any],
        hybrid_out:   Dict[str, Any],
        risk_profile: Optional[Dict[str, Any]] = None,
        uncertainty:  Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Simulate failure modes for the current treatment plan.

        Args:
            patient:      Raw patient dict.
            hybrid_out:   Output from hybrid engine (includes treatment_intent,
                          modulation from Step 3).
            risk_profile: Output from quant layer (Step 2). If None, falls back
                          to reading patient fields directly (degraded mode).
            uncertainty:  Output from uncertainty mapper (Step 4). Used to
                          modulate confidence of failure predictions.

        Returns:
            {
                "failures":          [failure_entry],
                "early_warning_signs": [str],   — deduplicated across all modes
                "exit_strategies":   [str],     — deduplicated across all modes
                "monitoring_plan":   [str],     — what to watch and when
                "overall_risk":      str,       — High | Moderate | Low
                "basis":             "structured_estimate",
            }

            failure_entry = {
                "mode":           str,
                "confidence":     str,   — likely | possible | watch
                "early_signs":    [str],
                "exit_strategy":  str,
            }
        """
        rp           = risk_profile or {}
        unc          = uncertainty  or {}
        penalty_score = unc.get("penalty_score", 0)

        # Read risk levels from quant layer (Step 2 output)
        cardiac_level  = rp.get("cardiac_risk",              {}).get("level", "Unknown")
        renal_level    = rp.get("renal_risk",                {}).get("level", "Unknown")
        toxicity_level = rp.get("toxicity_risk",             {}).get("level", "Unknown")
        disc_level     = rp.get("treatment_discontinuation", {}).get("level", "Unknown")

        # Read intent from hybrid_out (Step 3 output)
        intent_data = hybrid_out.get("treatment_intent") or {}
        intent      = intent_data.get("intent", "balanced")

        # Read patient context fields that aren't in quant layer
        social_support = (patient.get("social_support") or "adequate").lower()
        ecog           = patient.get("ecog", 1) or 1
        age            = patient.get("age")

        failures:   List[Dict[str, Any]] = []
        all_signs:  List[str] = []
        all_exits:  List[str] = []
        monitoring: List[str] = []

        # ── 1. Treatment intolerance ──────────────────────────────────────
        if toxicity_level in ("Very High", "High") or ecog >= 2:
            conf = _CONFIDENCE_LIKELY if toxicity_level == "Very High" else _CONFIDENCE_POSSIBLE
            conf = _confidence_from_penalty(conf, penalty_score)

            signs = [
                "Fatigue worsening week-on-week",
                "Drop in ECOG performance status by ≥1 grade",
                "Dose delays or reductions in first 2 cycles",
            ]
            if cardiac_level in ("Very High", "High"):
                signs.append("Worsening dyspnoea or new peripheral oedema")
            if renal_level in ("Very High", "High"):
                signs.append("Rising creatinine or eGFR decline >20% from baseline")

            exit_strat = (
                "Reduce dose intensity or switch to single-agent regimen. "
                "Increase monitoring to weekly labs for first 2 cycles."
            )

            failures.append({
                "mode":          "Treatment intolerance",
                "confidence":    conf,
                "early_signs":   signs,
                "exit_strategy": exit_strat,
            })
            all_signs.extend(signs)
            all_exits.append(exit_strat)
            monitoring.append("ECOG + labs (FBC, CMP) at each cycle for first 3 cycles")

        # ── 2. Suboptimal tumour control ──────────────────────────────────
        if intent in ("de-escalation", "palliative"):
            conf  = _CONFIDENCE_POSSIBLE
            conf  = _confidence_from_penalty(conf, penalty_score)

            signs = [
                "Radiologic progression at first restaging (6–8 weeks)",
                "Rising tumour markers (CEA, CA 19-9, PSA as applicable)",
                "New or worsening disease-related symptoms",
            ]
            exit_strat = (
                "Re-evaluate intent vs disease aggression at first restaging. "
                "Escalate therapy if functional status permits and patient consents."
            )

            failures.append({
                "mode":          "Suboptimal tumour control",
                "confidence":    conf,
                "early_signs":   signs,
                "exit_strategy": exit_strat,
            })
            all_signs.extend(signs)
            all_exits.append(exit_strat)
            monitoring.append("Restaging imaging at 6–8 weeks (CT CAP ± PET)")
            monitoring.append("Tumour marker trend at each cycle")

        # ── 3. Treatment discontinuation (social / adherence) ─────────────
        if social_support == "poor" or disc_level in ("Very High", "High"):
            conf  = _CONFIDENCE_POSSIBLE
            conf  = _confidence_from_penalty(conf, penalty_score)

            signs = [
                "Missed clinic appointments",
                "Delayed or skipped treatment cycles",
                "Medication non-adherence (oral agents)",
                "Patient reporting inability to attend due to logistics",
            ]
            exit_strat = (
                "Engage oncology social worker and community support services. "
                "Simplify regimen if equivalent options exist. "
                "Consider oral-only or less-frequent IV schedule."
            )

            failures.append({
                "mode":          "Treatment discontinuation (social/adherence)",
                "confidence":    conf,
                "early_signs":   signs,
                "exit_strategy": exit_strat,
            })
            all_signs.extend(signs)
            all_exits.append(exit_strat)
            monitoring.append("Attendance tracking + phone follow-up after each missed appointment")

        # ── 4. Cardiac decompensation ─────────────────────────────────────
        if cardiac_level in ("Very High", "High"):
            conf  = _CONFIDENCE_LIKELY if cardiac_level == "Very High" else _CONFIDENCE_POSSIBLE
            conf  = _confidence_from_penalty(conf, penalty_score)

            signs = [
                "New or worsening shortness of breath on exertion",
                "Peripheral oedema or rapid weight gain (>2 kg in 48h)",
                "EF drop >10% on repeat echocardiogram",
                "Chest pain or palpitations",
            ]
            exit_strat = (
                "Pause cardiotoxic therapy immediately. "
                "Urgent cardiology review. "
                "Consider cardio-oncology multidisciplinary input before restarting."
            )

            failures.append({
                "mode":          "Cardiac decompensation",
                "confidence":    conf,
                "early_signs":   signs,
                "exit_strategy": exit_strat,
            })
            all_signs.extend(signs)
            all_exits.append(exit_strat)
            monitoring.append("Echocardiogram at baseline, 3 months, and 6 months")
            monitoring.append("BNP / NT-proBNP if symptomatic cardiac concern arises")

        # ── 5. Renal failure progression ──────────────────────────────────
        if renal_level in ("Very High", "High"):
            conf  = _CONFIDENCE_LIKELY if renal_level == "Very High" else _CONFIDENCE_POSSIBLE
            conf  = _confidence_from_penalty(conf, penalty_score)

            signs = [
                "Creatinine rise >1.5× baseline",
                "eGFR decline >25% from baseline over 4 weeks",
                "Electrolyte imbalance (hyperkalaemia, hyponatraemia)",
                "Oliguria or unexpected fluid retention",
            ]
            exit_strat = (
                "Adjust or hold nephrotoxic agents immediately. "
                "Nephrology consult if eGFR drops below 30. "
                "Recalculate carboplatin AUC dosing with updated eGFR."
            )

            failures.append({
                "mode":          "Renal failure progression",
                "confidence":    conf,
                "early_signs":   signs,
                "exit_strategy": exit_strat,
            })
            all_signs.extend(signs)
            all_exits.append(exit_strat)
            monitoring.append("eGFR + electrolytes before each treatment cycle")

        # ── 6. Uncertainty-driven error ───────────────────────────────────
        if penalty_score >= 60:
            signs = [
                "Unexpected toxicity from undetected contraindicated pathway",
                "Treatment selection later found inappropriate for actual biomarker status",
                "Missing staging data leads to under- or over-treatment",
            ]
            exit_strat = (
                "Resolve all critical data gaps before next treatment cycle. "
                "Consider holding treatment until missing profiling is available."
            )

            failures.append({
                "mode":          "Uncertainty-driven clinical error",
                "confidence":    _CONFIDENCE_WATCH,
                "early_signs":   signs,
                "exit_strategy": exit_strat,
            })
            all_signs.extend(signs)
            all_exits.append(exit_strat)
            crit_gaps = unc.get("missing_critical", [])
            if crit_gaps:
                monitoring.append(
                    f"Resolve before proceeding: {'; '.join(crit_gaps)}"
                )

        # ── Aggregate ─────────────────────────────────────────────────────
        # Deduplicate while preserving order
        seen_signs  = set()
        seen_exits  = set()
        seen_mon    = set()
        unique_signs = [s for s in all_signs  if not (s in seen_signs  or seen_signs.add(s))]
        unique_exits = [e for e in all_exits  if not (e in seen_exits  or seen_exits.add(e))]
        unique_mon   = [m for m in monitoring if not (m in seen_mon    or seen_mon.add(m))]

        # Overall risk summary
        likely_count = sum(1 for f in failures if f["confidence"] == _CONFIDENCE_LIKELY)
        if likely_count >= 2:
            overall_risk = "High"
        elif likely_count == 1 or len(failures) >= 3:
            overall_risk = "Moderate"
        elif failures:
            overall_risk = "Low"
        else:
            overall_risk = "Minimal"

        logger.info(
            "FailureSimulator: modes=%d likely=%d overall=%s penalty=%d",
            len(failures), likely_count, overall_risk, penalty_score
        )

        return {
            "failures":            failures,
            "early_warning_signs": unique_signs,
            "exit_strategies":     unique_exits,
            "monitoring_plan":     unique_mon,
            "overall_risk":        overall_risk,
            "basis":               "structured_estimate",
            "disclaimer": (
                "Failure modes are structured predictions based on patient parameters and "
                "risk scores. They are NOT clinical trial outcome data. "
                "Validate against clinical judgement and patient-specific context."
            ),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

FAILURE_SIMULATOR = FailureSimulator()
