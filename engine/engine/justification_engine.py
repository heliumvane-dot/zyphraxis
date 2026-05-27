"""
justification_engine.py — Zyphraxis Phase 6C: Justification Engine

For every treatment considered, produces:
  - why_considered  : clinical rationale for inclusion in the option set
  - why_rejected    : exact reason it was not selected (if applicable)

For the final selected treatment:
  - why_selected    : full clinical justification
  - why_superior    : why this option outperforms every alternative

References biomarkers, CNS status, prior therapy, safety constraints,
resistance mutations, and evidence levels.

Output is structured for the ## JUSTIFICATION section of the final plan.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Modality → human-readable label
# ---------------------------------------------------------------------------
_MODALITY_LABELS: Dict[str, str] = {
    "targeted":  "targeted therapy (TKI / small-molecule inhibitor)",
    "immuno":    "immune checkpoint inhibitor (IO)",
    "chemo":     "cytotoxic chemotherapy",
    "radio":     "radiotherapy",
    "hormone":   "endocrine / hormonal therapy",
    "parp":      "PARP inhibitor",
    "combo":     "combination regimen",
}


class JustificationEngine:
    """
    Generates full natural-language justifications for every treatment option
    and for the final hybrid selection.

    Usage:
        je = JustificationEngine()
        report = je.generate(
            all_options      = list_of_all_treatment_dicts,
            rejected_options = list_of_RejectedTreatment_objects,  # from eligibility filter
            final_selection  = hybrid_engine_output,
            hybrid_debug     = hybrid_output["_debug"],
            patient_context  = patient_dict,
        )
    """

    def generate(
        self,
        all_options:      List[Dict[str, Any]],
        rejected_options: List[Any],           # RejectedTreatment dataclass instances or dicts
        final_selection:  Dict[str, Any],
        hybrid_debug:     Dict[str, Any],
        patient_context:  Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Returns:
        {
            "options": [
                {
                    "name":           str,
                    "why_considered": str,
                    "why_rejected":   str | None,   # None = not rejected
                }
            ],
            "final": {
                "name":          str,
                "why_selected":  str,
                "why_superior":  str,
            },
            "safety_warnings": [str],
        }
        """
        ctx = patient_context or {}

        final_name      = final_selection.get("final_regimen", "")
        ranked          = hybrid_debug.get("ranked", [])
        apollo_name     = hybrid_debug.get("apollo_name")
        manhattan_name  = hybrid_debug.get("manhattan_name")

        # Build rejection lookup from eligibility filter output
        rejection_map: Dict[str, str] = {}
        for r in (rejected_options or []):
            if isinstance(r, dict):
                rejection_map[r.get("treatment_name", "")] = r.get("rejection_reason", "")
            else:
                rejection_map[getattr(r, "treatment_name", "")] = getattr(r, "rejection_reason", "")

        # Build scoring-reason lookup from hybrid debug
        reason_map: Dict[str, List[str]] = {
            entry["name"]: entry.get("reasons", []) for entry in ranked
        }
        score_map: Dict[str, float] = {
            entry["name"]: entry.get("score", 0) for entry in ranked
        }

        # ── Per-option justifications ─────────────────────────────────────
        option_justifications = []
        all_names = {t["name"] for t in all_options}
        # Also include options that were considered but rejected by eligibility
        for r in (rejected_options or []):
            rname = r.get("treatment_name") if isinstance(r, dict) else getattr(r, "treatment_name", "")
            all_names.add(rname)

        for t in all_options:
            name          = t["name"]
            considered    = self._why_considered(t, ctx)
            reject_reason = rejection_map.get(name)
            hybrid_reasons = reason_map.get(name, [])

            if reject_reason:
                rejected = reject_reason
            elif name != final_name:
                rejected = self._why_not_selected(t, name, final_name, hybrid_reasons, ctx, score_map)
            else:
                rejected = None  # final selection

            option_justifications.append({
                "name":           name,
                "why_considered": considered,
                "why_rejected":   rejected,
            })

        # Add eligibility-rejected options not in main list
        for r in (rejected_options or []):
            rname = r.get("treatment_name") if isinstance(r, dict) else getattr(r, "treatment_name", "")
            rmod  = r.get("modality") if isinstance(r, dict) else getattr(r, "modality", "unknown")
            rreason = rejection_map.get(rname, "Did not meet eligibility criteria.")
            if not any(o["name"] == rname for o in option_justifications):
                option_justifications.append({
                    "name":           rname,
                    "why_considered": self._why_considered_from_modality(rmod, rname, ctx),
                    "why_rejected":   f"[ELIGIBILITY GATE] {rreason}",
                })

        # ── Final selection justification ────────────────────────────────
        final_treatment = next((t for t in all_options if t["name"] == final_name), None)
        final_reasons   = reason_map.get(final_name, [])

        why_selected = self._why_selected(
            final_treatment, final_name, final_reasons, ctx,
            apollo_name, manhattan_name,
        )
        why_superior = self._why_superior(
            final_name, final_reasons, option_justifications, ctx,
        )

        # ── Safety warnings ──────────────────────────────────────────────
        warnings = self._collect_warnings(all_options, rejected_options, ctx, hybrid_debug)

        return {
            "options":         option_justifications,
            "final": {
                "name":         final_name,
                "why_selected": why_selected,
                "why_superior": why_superior,
            },
            "safety_warnings": warnings,
        }

    # -----------------------------------------------------------------------
    # Why Considered
    # -----------------------------------------------------------------------

    def _why_considered(self, t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
        parts = []
        modality_label = _MODALITY_LABELS.get(t.get("modality", ""), t.get("modality", "treatment"))
        parts.append(
            f"{t['name']} is a {modality_label} with NCCN evidence level "
            f"{t.get('evidence_level', 'N/A')} (line {t.get('line_of_therapy', '?')})."
        )

        bm = t.get("required_biomarkers", {})
        if bm:
            bm_str = ", ".join(f"{k}={v}" for k, v in bm.items())
            parts.append(f"Requires biomarker confirmation: {bm_str}.")

        notes = t.get("notes")
        if notes:
            # Truncate notes to first sentence for brevity
            first_sentence = notes.split(".")[0].strip() + "."
            parts.append(first_sentence)

        ref = t.get("trial_reference")
        if ref:
            parts.append(f"Evidence basis: {ref}.")

        return " ".join(parts)

    def _why_considered_from_modality(self, modality: str, name: str, ctx: dict) -> str:
        label = _MODALITY_LABELS.get(modality, modality)
        return (
            f"{name} is a {label} that falls within the NCCL guideline set "
            f"for this cancer type and stage. It was evaluated against eligibility criteria."
        )

    # -----------------------------------------------------------------------
    # Why Not Selected (for options that passed eligibility but lost to hybrid)
    # -----------------------------------------------------------------------

    def _why_not_selected(
        self,
        t:               Dict[str, Any],
        name:            str,
        final_name:      str,
        hybrid_reasons:  List[str],
        ctx:             Dict[str, Any],
        score_map:       Dict[str, float],
    ) -> str:
        parts = []

        # IO rejection for EGFR+
        if "io_rejected_egfr_positive" in hybrid_reasons:
            parts.append(
                f"{name} is an immunotherapy agent. Per NCCN guidelines, IO monotherapy is "
                "contraindicated in EGFR-mutated NSCLC due to inferior outcomes and potential "
                "harm compared to EGFR-directed TKI therapy (KEYNOTE-024 subgroup analysis; "
                "IMpower110 EGFR subgroup). IO is therefore excluded."
            )
            return " ".join(parts)

        # Lower score explanation
        final_score  = score_map.get(final_name, 0)
        option_score = score_map.get(name, 0)
        delta        = final_score - option_score

        if "driver_mutation_match" not in hybrid_reasons and ctx.get("driver_mutation"):
            driver = ctx.get("driver_mutation", "").upper()
            parts.append(
                f"{name} does not directly target the {driver} driver mutation identified in this patient, "
                f"making it a less optimal choice than mutation-matched targeted therapy."
            )

        if "cns_active" not in hybrid_reasons and (ctx.get("brain_mets") or ctx.get("cns_disease")):
            parts.append(
                f"{name} has limited CNS penetration and is therefore suboptimal given documented "
                "brain metastases or CNS disease in this patient."
            )

        if "resistance_matched" not in hybrid_reasons and ctx.get("resistance_mutation"):
            parts.append(
                f"{name} does not address the acquired resistance mutation "
                f"({ctx['resistance_mutation']}) identified on re-biopsy."
            )

        ev_rank = {"1A": 4, "1B": 3, "2A": 2, "2B": 1, "3": 0}
        t_ev    = ev_rank.get(t.get("evidence_level", ""), 0)
        final_t = None  # We may not have it here — handled generically
        if t_ev < 3:
            parts.append(
                f"Evidence level {t.get('evidence_level', 'unknown')} is lower than the preferred "
                "guideline evidence tier (1A/1B) for first-line treatment in this setting."
            )

        if not parts:
            parts.append(
                f"{name} was outscored by {final_name} in the hybrid arbitration pipeline "
                f"(priority score gap: {delta:.0f}). It remains a clinically valid alternative "
                "if the selected regimen is not tolerated."
            )

        return " ".join(parts)

    # -----------------------------------------------------------------------
    # Why Selected (final treatment)
    # -----------------------------------------------------------------------

    def _why_selected(
        self,
        t:              Optional[Dict[str, Any]],
        name:           str,
        reasons:        List[str],
        ctx:            Dict[str, Any],
        apollo_name:    Optional[str],
        manhattan_name: Optional[str],
    ) -> str:
        parts = []

        if "resistance_matched" in reasons:
            rm = ctx.get("resistance_mutation") or ctx.get("acquired_resistance")
            parts.append(
                f"{name} is specifically indicated for the acquired resistance mutation "
                f"({rm}) identified on re-biopsy, providing the highest clinical priority override."
            )

        if "cns_active" in reasons:
            parts.append(
                f"{name} demonstrates superior CNS penetration, making it the preferred agent "
                "in the setting of documented brain metastases or CNS progression."
            )

        if "driver_mutation_match" in reasons:
            driver = (ctx.get("driver_mutation") or ctx.get("mutation", "")).upper()
            parts.append(
                f"{name} is a biomarker-directed targeted therapy matched to the {driver} "
                "driver alteration confirmed by molecular profiling, consistent with NCCN "
                "Category 1A recommendation for driver-mutation-positive NSCLC."
            )

        if "io_rejected_egfr_positive" not in reasons and ctx.get("biomarkers", {}).get("PD-L1") and not (ctx.get("driver_mutation") or ctx.get("mutation")):
            parts.append(
                f"In the absence of an actionable driver mutation, high PD-L1 expression "
                "supports selection of immune checkpoint inhibitor therapy per KEYNOTE-024."
            )

        if "both_modes_agree" in reasons:
            parts.append(
                f"Both Apollo (conservative) and Manhattan (aggressive) modes independently "
                "selected this regimen, indicating strong cross-modal consensus."
            )
        elif apollo_name == name:
            parts.append(
                "The Apollo (conservative/safety-weighted) mode independently selected this "
                "regimen, supporting the final hybrid decision."
            )

        if t:
            ev   = t.get("evidence_level", "")
            ref  = t.get("trial_reference", "")
            line = t.get("line_of_therapy", 1)
            parts.append(
                f"NCCN evidence level {ev}, line {line} therapy. "
                f"Trial basis: {ref}." if ref else f"NCCN evidence level {ev}, line {line} therapy."
            )

        if "biomarker_match" in reasons:
            parts.append(
                "Biomarker panel confirms the required molecular prerequisite for this regimen, "
                "reducing empiric uncertainty."
            )

        if not parts:
            parts.append(
                f"{name} achieved the highest priority score in the hybrid arbitration pipeline, "
                "balancing safety, efficacy, evidence level, and mode consensus."
            )

        return " ".join(parts)

    # -----------------------------------------------------------------------
    # Why Superior
    # -----------------------------------------------------------------------

    def _why_superior(
        self,
        final_name:            str,
        reasons:               List[str],
        option_justifications: List[Dict],
        ctx:                   Dict[str, Any],
    ) -> str:
        alternatives = [
            o["name"] for o in option_justifications
            if o["name"] != final_name
        ]
        if not alternatives:
            return f"{final_name} is the sole eligible option after safety and eligibility filtering."

        alt_str = "; ".join(alternatives[:4])
        parts   = []

        if "resistance_matched" in reasons:
            parts.append(
                f"Compared to alternatives ({alt_str}), {final_name} is the only agent "
                "with demonstrated activity against the specific resistance mechanism "
                "present in this patient. Alternative agents would be expected to have "
                "diminished or absent efficacy in this molecular context."
            )

        elif "cns_active" in reasons:
            parts.append(
                f"Compared to alternatives ({alt_str}), {final_name} achieves adequate "
                "CNS penetration to treat intracranial disease — a critical requirement "
                "for this patient. Agents without CNS activity would fail to control "
                "brain metastases even if systemic disease responds."
            )

        elif "driver_mutation_match" in reasons:
            driver = (ctx.get("driver_mutation") or ctx.get("mutation", "")).upper()
            parts.append(
                f"Compared to alternatives ({alt_str}), {final_name} directly targets "
                f"the {driver} oncogenic driver, achieving superior ORR and PFS in "
                "driver-positive populations as demonstrated in randomised phase III trials. "
                "Non-targeted alternatives carry substantially inferior response rates "
                "in biomarker-selected populations."
            )

        if "io_rejected_egfr_positive" not in reasons and ctx.get("driver_mutation"):
            parts.append(
                "IO-based regimens are specifically excluded because driver-positive patients "
                "derive no benefit and may experience accelerated progression on immune checkpoint "
                "inhibition without concomitant targeted therapy."
            )

        if not parts:
            parts.append(
                f"{final_name} outperforms alternatives ({alt_str}) across the composite "
                "priority framework: resistance specificity, CNS coverage, biomarker matching, "
                "evidence grade, and mode consensus scoring."
            )

        return " ".join(parts)

    # -----------------------------------------------------------------------
    # Safety Warnings
    # -----------------------------------------------------------------------

    def _collect_warnings(
        self,
        all_options:     List[Dict[str, Any]],
        rejected_options: List[Any],
        ctx:             Dict[str, Any],
        hybrid_debug:    Dict[str, Any],
    ) -> List[str]:
        warnings = []

        # Cisplatin / renal constraint
        crcl = ctx.get("creatinine_clearance")
        if crcl is not None and crcl < 60:
            warnings.append(
                f"⚠️  RENAL FUNCTION: Creatinine clearance = {crcl} mL/min. "
                "Cisplatin is contraindicated (requires CrCl ≥60 mL/min). "
                "Carboplatin-based substitution is appropriate if platinum is indicated. "
                "Pemetrexed requires CrCl ≥45 mL/min."
            )

        # EGFR + IO warning
        biomarkers    = ctx.get("biomarkers", {})
        egfr_positive = str(biomarkers.get("EGFR", "")).lower() in ("positive", "mutated", "true", "yes")
        if egfr_positive:
            warnings.append(
                "⚠️  IO CONTRAINDICATION: EGFR-mutated NSCLC. Immune checkpoint inhibitor "
                "monotherapy is not recommended as first-line therapy. Published data "
                "(IMpower110, KEYNOTE-024 EGFR subgroup) show no benefit and potential "
                "harm. Osimertinib or appropriate EGFR TKI is preferred."
            )

        # Brain mets reminder
        if ctx.get("brain_mets") or ctx.get("cns_disease"):
            warnings.append(
                "⚠️  CNS DISEASE: Brain metastases documented. Confirm that selected regimen "
                "has adequate intracranial penetration. Baseline brain MRI before treatment "
                "initiation is strongly recommended. Radiation oncology consultation advised "
                "for symptomatic or large lesions."
            )

        # T790M resistance
        if ctx.get("resistance_mutation") == "T790M" or "T790M" in str(ctx.get("biomarkers", "")):
            warnings.append(
                "⚠️  ACQUIRED RESISTANCE (T790M): T790M mutation detected on re-biopsy or "
                "liquid biopsy. First-generation EGFR TKIs (erlotinib, gefitinib, afatinib) "
                "are expected to be ineffective. Osimertinib (third-generation TKI) is the "
                "evidence-based choice for T790M+ second-line therapy (AURA3, NEJM 2017)."
            )

        # Low ECOG warning
        ecog = ctx.get("ecog_status")
        if ecog is not None and ecog >= 3:
            warnings.append(
                f"⚠️  PERFORMANCE STATUS: ECOG PS = {ecog}. Most cytotoxic regimens are "
                "contraindicated at ECOG ≥3. Supportive care and goals-of-care discussion "
                "are strongly advised before initiating systemic therapy."
            )

        # Missing biomarkers
        if not biomarkers:
            warnings.append(
                "⚠️  INCOMPLETE BIOMARKER DATA: No biomarker results provided. "
                "Comprehensive molecular profiling (EGFR, ALK, ROS1, PD-L1, KRAS, BRAF, "
                "MET, RET, NTRK) is required before initiating targeted therapy. "
                "Current recommendation is provisional pending biomarker confirmation."
            )

        # Rejected options with safety implications
        for r in (rejected_options or []):
            reason = r.get("rejection_reason") if isinstance(r, dict) else getattr(r, "rejection_reason", "")
            rname  = r.get("treatment_name") if isinstance(r, dict) else getattr(r, "treatment_name", "")
            if "cisplatin" in rname.lower() and "renal" in reason.lower():
                warnings.append(
                    f"⚠️  {rname} was excluded: {reason}"
                )

        return warnings
