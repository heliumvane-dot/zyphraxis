"""
pipeline_integration.py — Zyphraxis Phase 9: Full Clinical Decision Pipeline

Phase 9 pipeline:
  PatientSchema
    → Clinical Guardrails (validate_case)  [Phase 9 — safety gate]
    → Uncertainty Mapper                  [Phase 9 — missing data detection]
    → Patient Intent Engine               [Phase 9 — treatment aggressiveness]
    → PolicyEngine.get_options()          [Phase 6A — guideline option universe]
    → ConstraintEngine.filter()           [Phase 6A — organ/marrow/CNS safety]
    → ApolloMode.decide()                 [Phase 6B — fast intent-aware pick]
    → ManhattanMode.evaluate()            [Phase 6B — deep intent-aware evaluation]
    → HybridEngine.select()               [Phase 6C — arbitration]
    → JustificationEngine.generate()      [Phase 6C — audit + explanation]
    → Intent Modulation                   [Phase 9 — apply intent to output]
    → Quant Layer                         [Phase 9 — risk quantification]
    → Failure Simulator                   [Phase 9 — failure prediction]
    → Final Explainable Output

Phase 5 compatibility:
  Accepts EITHER the Phase 6A patient schema (disease/biomarkers/organ_function)
  OR the Phase 5-style schema (cancer_type/biomarkers dict with string keys).
  Normalisation is handled in _normalise_patient() — no callers need to change.

Call run_phase6(patient) from your API route or tests.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import sys
import os

# ── Path bootstrap ────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in [_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine.hybrid_engine        import HybridEngine
from engine.justification_engine import JustificationEngine
from engine.quant_layer          import QUANT_LAYER
from clinical.patient_intent     import INTENT_ENGINE
from engine.uncertainty_mapper   import UNCERTAINTY_MAPPER
from engine.failure_simulator    import FAILURE_SIMULATOR
from engine.treatment_schema     import Treatment
from engine.cancers.lung         import LUNG_TREATMENTS
from clinical.policy_engine      import load_policy_engine
from clinical.constraint_engine  import ConstraintEngine
from clinical.apollo_mode        import ApolloMode
from clinical.manhattan_mode     import ManhattanMode


# ---------------------------------------------------------------------------
# Module-level singletons (loaded once at import — fail-fast on bad YAML)
# ---------------------------------------------------------------------------

_POLICY     = load_policy_engine()
_CONSTRAINT = ConstraintEngine()
_APOLLO     = ApolloMode()
_MANHATTAN  = ManhattanMode()


# ---------------------------------------------------------------------------
# Patient schema normalisation
# ---------------------------------------------------------------------------

def _normalise_patient(patient: dict) -> dict:
    """
    Accept either Phase 6A or Phase 5-style patient dicts and return a unified
    Phase 6A-format dict that all engines can consume.

    Phase 5-style keys mapped:
        cancer_type         → disease
        biomarkers (str-keyed EGFR/ALK/etc.)  → biomarkers (bool-keyed)
        creatinine_clearance → organ_function.renal (derived category)
        driver_mutation / mutation → biomarkers
        brain_mets / cns_disease   → brain_mets
        resistance_mutation         → egfr_t790m + progression_type
        line                        → progression_type
        contraindications           → organ_function.renal gate (if severe_renal)
        ecog_status                 → ecog
    """
    # Already Phase 6A format?
    if "disease" in patient:
        return dict(patient)

    raw_biomarkers = patient.get("biomarkers", {})

    def _truthy(val) -> bool:
        return str(val).lower() in ("positive", "mutated", "true", "yes", "1")

    # Map string-keyed biomarkers → Phase 6A bool-keyed biomarkers
    egfr  = _truthy(raw_biomarkers.get("EGFR", False))
    alk   = _truthy(raw_biomarkers.get("ALK", False))
    ros1  = _truthy(raw_biomarkers.get("ROS1", False))
    t790m = _truthy(raw_biomarkers.get("T790M", False))

    # PD-L1 may arrive as float (0.75), int (75), or string ("positive"/"negative")
    # "positive" without a numeric value → fall back to top-level pdl1 field or 0
    _pdl1_raw = raw_biomarkers.get("PD-L1", raw_biomarkers.get("pdl1", 0)) or 0
    if isinstance(_pdl1_raw, str) and not _pdl1_raw.replace(".", "").isdigit():
        # string like "positive" / "negative" — use top-level pdl1 if present
        pdl1 = float(patient.get("pdl1", 0) or 0)
    else:
        pdl1 = float(_pdl1_raw)

    # Also infer from driver_mutation / mutation field
    driver = (patient.get("driver_mutation") or patient.get("mutation") or "").upper()
    if driver == "EGFR":
        egfr = True
    elif driver == "ALK":
        alk = True
    elif driver == "ROS1":
        ros1 = True

    # Resistance mutation → T790M + progression line
    resistance = patient.get("resistance_mutation")
    if resistance == "T790M":
        t790m = True

    # Line → progression_type
    line             = patient.get("line", 1) or 1
    progression_type = "progression" if line >= 2 else None

    # Creatinine clearance → renal organ function category
    crcl = patient.get("creatinine_clearance")
    if crcl is None:
        renal = "normal"
    elif crcl < 30:
        renal = "severe"
    elif crcl < 60:
        renal = "moderate"
    else:
        renal = "normal"

    # Contraindications can override renal
    contras = [c.lower() for c in patient.get("contraindications", [])]
    if "severe_renal" in contras or "renal" in contras:
        renal = "severe"

    # Marrow suppression from contraindications
    marrow_status = "normal"
    if any(c in contras for c in ("marrow_suppression", "myelosuppression", "bone_marrow")):
        marrow_status = "suppressed"

    # Brain mets
    brain_mets = bool(patient.get("brain_mets", False) or patient.get("cns_disease", False))

    # ECOG
    ecog = patient.get("ecog_status", patient.get("ecog", 1))

    # Disease burden
    burden = patient.get("disease_burden", "moderate")

    return {
        "disease":                  (patient.get("cancer_type") or "lung").lower(),
        "stage":                    patient.get("stage", "IV"),
        "ecog":                     ecog,
        "biomarkers": {
            "egfr_mutation":        egfr,
            "alk_rearrangement":    alk,
            "ros1_fusion":          ros1,
            "pd_l1":                pdl1,
            "egfr_t790m":           t790m,
        },
        "organ_function":           {"renal": renal, "hepatic": "normal"},
        "marrow_status":            marrow_status,
        "prior_therapy":            patient.get("prior_therapies"),
        "progression_type":         progression_type,
        "brain_mets":               brain_mets,
        "brain_mets_symptomatic":   bool(patient.get("brain_mets_symptomatic", False)),
        "disease_burden":           burden,
        # Preserve original for HybridEngine (which uses Phase 5 string-keyed biomarkers)
        "_raw":                     patient,
    }


# ---------------------------------------------------------------------------
# Legacy eligibility filter — LUNG_TREATMENTS catalogue
# Used by HybridEngine and JustificationEngine
# ---------------------------------------------------------------------------

def _prior_therapy_guard(treatment: dict, prior_therapies: list) -> tuple:
    """
    PHASE 10 FIX (Issue 2): Check if treatment duplicates a prior therapy.

    Uses drug-name prefix matching: extracts the canonical drug name(s) from
    both the proposed treatment and each prior therapy, then checks for overlap.
    This ensures "Osimertinib 2L (T790M+)" is blocked when "Osimertinib 1L"
    was previously given, while allowing different drugs like "Lorlatinib" after
    "Alectinib".

    Matching logic:
      1. Normalise to lowercase.
      2. Strip line/dose suffixes (e.g. "1L", "2L", "(T790M+)", "(ALK 2L+)").
      3. Split on " + " to handle combo regimens and check any component overlap.

    Returns (is_excluded: bool, reason: str | None).
    """
    import re

    if not prior_therapies:
        return False, None

    def _drug_tokens(name: str) -> set:
        """Return the set of core drug-name tokens from a regimen string."""
        # Lowercase
        s = name.lower()
        # Remove parenthesised suffixes like (t790m+), (alk 2l+)
        s = re.sub(r"\([^)]*\)", "", s)
        # Remove standalone line markers: 1l, 2l, 3l, 1st, 2nd, 3rd
        s = re.sub(r"\b\d+l\b", "", s)
        s = re.sub(r"\b(first|second|third|1st|2nd|3rd)-line\b", "", s)
        # Split on " + " (combo separator) and on whitespace
        parts = re.split(r"\s*\+\s*|\s+", s)
        # Keep only non-trivial tokens (length > 2)
        return {p.strip() for p in parts if len(p.strip()) > 2}

    treatment_name = treatment.get("name", "")
    if not treatment_name:
        return False, None

    treat_tokens = _drug_tokens(treatment_name)
    if not treat_tokens:
        return False, None

    for prior in prior_therapies:
        if not prior:
            continue
        prior_tokens = _drug_tokens(prior)
        if treat_tokens & prior_tokens:  # any common drug token
            return True, f"Prior therapy: {prior} — already received (drug-name match)"

    return False, None


def _build_safe_options(patient: dict) -> tuple:
    """
    Biomarker + organ-function + prior-therapy eligibility filter over LUNG_TREATMENTS.
    Returns (eligible_list, rejected_list).

    PHASE 10: Now also excludes treatments that match prior_therapies (Fix Issue 2).
    """
    raw        = patient.get("_raw", patient)
    biomarkers = raw.get("biomarkers", {})
    crcl       = raw.get("creatinine_clearance")
    contras    = [c.lower() for c in raw.get("contraindications", [])]
    line       = raw.get("line", 1) or 1
    resistance = raw.get("resistance_mutation")

    # [PHASE 10] Resolve prior therapies from normalised patient dict
    prior_therapy = patient.get("prior_therapy") or raw.get("prior_therapies", [])
    if isinstance(prior_therapy, str):
        prior_therapy = [prior_therapy]
    elif not isinstance(prior_therapy, list):
        prior_therapy = []

    treatments = [t.to_dict() for t in LUNG_TREATMENTS]

    # Inject T790M 2L entry when applicable
    t790m_name = "Osimertinib 2L (T790M+)"
    if resistance == "T790M" and line == 2:
        if not any(t["name"] == t790m_name for t in treatments):
            t790m = Treatment(
                name                  = t790m_name,
                cancer_type           = "lung",
                stages                = ["III", "IV"],
                duration_h            = 504,
                trial_orr             = 0.71,
                grade34_toxicity_rate = 0.23,
                evidence_level        = "1A",
                line_of_therapy       = 2,
                cost                  = 58_000,
                modality              = "targeted",
                required_biomarkers   = {"EGFR": "positive", "T790M": "positive"},
                organ_function_gates  = {"creatinine_clearance_min": 15},
                notes                 = "Second-line T790M+ NSCLC. AURA3: ORR 71%.",
                trial_reference       = "AURA3 (NEJM 2017; DOI:10.1056/NEJMoa1612674)",
            )
            treatments = [t790m.to_dict()] + treatments

    def _egfr_positive(bm: dict) -> bool:
        return str(bm.get("EGFR", "")).lower() in ("positive", "mutated", "true", "yes")

    eligible: list = []
    rejected: list = []

    for t in treatments:
        reject_reason = None

        # [PHASE 10] Prior therapy guard — fail fast before biomarker checks
        is_prior, prior_reason = _prior_therapy_guard(t, prior_therapy)
        if is_prior:
            reject_reason = prior_reason

        # Biomarker gating
        for marker, needed in (t.get("required_biomarkers", {}).items() if not reject_reason else []):
            patient_val = biomarkers.get(marker, "")
            if not patient_val:
                reject_reason = f"Required biomarker {marker} not confirmed in patient record."
                break
            if str(patient_val).lower() not in (
                str(needed).lower(), "positive", "mutated", "true", "yes"
            ):
                reject_reason = (
                    f"Biomarker {marker} is {patient_val} (required: {needed}). "
                    "Treatment not indicated."
                )
                break

        # Organ function gates
        if not reject_reason:
            min_crcl = t.get("organ_function_gates", {}).get("creatinine_clearance_min")
            if min_crcl and crcl is not None and crcl < min_crcl:
                reject_reason = (
                    f"CrCl {crcl} mL/min is below the minimum {min_crcl} mL/min required "
                    f"for {t['name']}. Renal function gate failed."
                )

        # Contraindications
        if not reject_reason:
            for c in t.get("contraindications", []):
                if c.lower() in contras:
                    reject_reason = f"Patient contraindication: {c}."
                    break

        # EGFR+ IO rejection (line 1)
        if not reject_reason:
            if t.get("modality") == "immuno" and _egfr_positive(biomarkers):
                if t.get("line_of_therapy", 1) == 1:
                    reject_reason = (
                        "IO monotherapy contraindicated for EGFR-mutated NSCLC first-line. "
                        "No benefit demonstrated (IMpower110, KEYNOTE-024 EGFR subgroup). "
                        "EGFR TKI is preferred."
                    )

        if reject_reason:
            rejected.append({
                "treatment_name":   t["name"],
                "modality":         t.get("modality", "unknown"),
                "rejection_reason": reject_reason,
            })
        else:
            eligible.append(t)

    return eligible, rejected


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def _format_output(
    apollo_out:         dict,
    manhattan_out,
    hybrid_out:         dict,
    justification:      dict,
    policy_space:       list,
    risk_profile:       dict = None,
    uncertainty:        dict = None,
    guardrail:          dict = None,
    failure_simulation: dict = None,
) -> str:
    lines = []

    lines.append("## APOLLO MODE")
    regimen = apollo_out.get("final_regimen") or apollo_out.get("choice", "N/A")
    lines.append(f"  Regimen    : {regimen}")
    lines.append(f"  Confidence : {apollo_out.get('confidence', 0):.2f}")
    reason = apollo_out.get("reason", "")
    if reason:
        lines.append(f"  Reason     : {reason}")
    lines.append("")

    lines.append("## MANHATTAN MODE")
    if isinstance(manhattan_out, list) and manhattan_out:
        top = manhattan_out[0]
        lines.append(f"  Regimen    : {top.get('regimen', 'N/A')}  (rank 1 of {len(manhattan_out)})")
        lines.append(f"  Score      : {top.get('score', '?')}")
        if top.get("pros"):
            lines.append(f"  Pros       : {'; '.join(top['pros'][:2])}")
        if top.get("cons"):
            lines.append(f"  Cons       : {'; '.join(top['cons'][:1])}")
    elif isinstance(manhattan_out, dict):
        lines.append(f"  Regimen    : {manhattan_out.get('final_regimen', 'N/A')}")
        lines.append(f"  Confidence : {manhattan_out.get('confidence', 0):.2f}")
    lines.append("")

    lines.append("## HYBRID DECISION")
    lines.append(f"  Regimen    : {hybrid_out.get('final_regimen', 'N/A')}")
    lines.append(f"  Line       : {hybrid_out.get('line', '?')}")
    lines.append(f"  Confidence : {hybrid_out.get('confidence', 0):.2f}")
    lines.append("")

    # ── Phase 9: Treatment intent ──────────────────────────────────────────
    intent_data = hybrid_out.get("treatment_intent")
    if intent_data:
        lines.append("## TREATMENT INTENT")
        lines.append(f"  Intent     : {intent_data.get('intent', 'N/A').upper()}")
        lines.append(f"  Confidence : {intent_data.get('confidence', 'N/A')}")
        lines.append(f"  Modulation : {hybrid_out.get('modulation', '')}")
        reasoning = intent_data.get("reasoning", [])
        if reasoning:
            lines.append("  Factors    :")
            for r in reasoning:
                lines.append(f"    — {r}")
        lines.append("")

    lines.append("### POLICY SPACE")
    for opt in policy_space:
        name   = opt.get("name", opt.get("regimen", "?"))
        marker = " ← SELECTED" if name == hybrid_out.get("final_regimen") else ""
        lines.append(f"  • {name}{marker}")
    lines.append("")

    lines.append("### FINAL PLAN")
    lines.append(f"  regimen    : {hybrid_out.get('final_regimen', 'N/A')}")
    lines.append(f"  line       : {hybrid_out.get('line', '?')}")
    lines.append(f"  confidence : {hybrid_out.get('confidence', 0):.2f}")
    lines.append("")

    lines.append("## JUSTIFICATION")
    fin = justification.get("final", {})
    lines.append(f"**Why Selected — {fin.get('name', '')}**")
    lines.append(f"  {fin.get('why_selected', '')}")
    lines.append("")
    lines.append("**Why Superior**")
    lines.append(f"  {fin.get('why_superior', '')}")
    lines.append("")
    lines.append("**All Options Considered**")
    for opt in justification.get("options", []):
        lines.append(f"  [{opt['name']}]")
        lines.append(f"    Considered : {opt.get('why_considered', '')}")
        if opt.get("why_rejected"):
            lines.append(f"    Rejected   : {opt['why_rejected']}")
        else:
            lines.append("    Rejected   : — (SELECTED)")
    lines.append("")

    # ── Phase 9: Uncertainty ──────────────────────────────────────────────────
    if uncertainty:
        penalty = uncertainty.get("confidence_penalty", "None")
        summary = uncertainty.get("uncertainty_summary", "")
        critical = uncertainty.get("missing_critical", [])
        moderate = uncertainty.get("missing_moderate", [])
        minor    = uncertainty.get("missing_minor", [])
        actions  = uncertainty.get("recommended_actions", [])

        lines.append("## UNCERTAINTY ASSESSMENT")
        lines.append(f"  Summary          : {summary}")
        lines.append(f"  Confidence penalty: {penalty}")

        if critical:
            lines.append("  Critical gaps    :")
            for g in critical:
                lines.append(f"    ⛔ {g}")
        if moderate:
            lines.append("  Moderate gaps    :")
            for g in moderate:
                lines.append(f"    ⚠  {g}")
        if minor:
            lines.append("  Minor gaps       :")
            for g in minor:
                lines.append(f"    ·  {g}")
        if actions:
            lines.append("  Recommended actions:")
            for a in actions:
                lines.append(f"    → {a}")
        lines.append("")

    # ── Phase 9: Risk Assessment ──────────────────────────────────────────────
    if risk_profile:
        lines.append("## RISK ASSESSMENT  [basis: structured_estimate — not clinical trial probabilities]")

        def _fmt_risk(label: str, d: dict) -> str:
            level = d.get("level", "Unknown")
            rng   = d.get("range", "N/A")
            note  = d.get("note", "")
            inp   = f"  [{d['input']}]" if d.get("input") else ""
            return f"  {label:<30} {level:<12} {rng}{inp}  — {note}"

        lines.append(_fmt_risk("Cardiac risk",               risk_profile.get("cardiac_risk", {})))
        lines.append(_fmt_risk("Renal risk",                 risk_profile.get("renal_risk", {})))
        lines.append(_fmt_risk("Chemo toxicity risk",        risk_profile.get("toxicity_risk", {})))
        lines.append(_fmt_risk("Treatment discontinuation",  risk_profile.get("treatment_discontinuation", {})))
        lines.append(f"  * {risk_profile.get('disclaimer', '')}")
        lines.append("")

    lines.append("## SAFETY WARNINGS")
    warnings = justification.get("safety_warnings", [])
    if warnings:
        for w in warnings:
            lines.append(f"  {w}")
    else:
        lines.append("  No critical safety warnings for this patient-regimen combination.")
    lines.append("")

    # ── Phase 9: Failure Simulation ───────────────────────────────────────────
    if failure_simulation:
        fs       = failure_simulation
        failures = fs.get("failures", [])
        overall  = fs.get("overall_risk", "Unknown")
        mon      = fs.get("monitoring_plan", [])

        _conf_icon = {
            "likely":   "🔴",
            "possible": "🟠",
            "watch":    "🟡",
        }

        lines.append(f"## FAILURE SIMULATION  [overall plan risk: {overall}]")

        if not failures:
            lines.append("  No significant failure modes predicted for this patient-plan combination.")
        else:
            for f in failures:
                icon = _conf_icon.get(f.get("confidence", "watch"), "·")
                lines.append(f"  {icon} {f['mode']}  [{f.get('confidence','?')}]")
                for s in f.get("early_signs", []):
                    lines.append(f"       Early sign  : {s}")
                lines.append(f"       Exit strategy: {f.get('exit_strategy','')}")
                lines.append("")

        if mon:
            lines.append("  Monitoring plan:")
            for m in mon:
                lines.append(f"    ⏱  {m}")
            lines.append("")

        lines.append(f"  * {fs.get('disclaimer', '')}")

    # Phase 9 — mandatory safety disclaimer (NEVER optional)
    lines.append("")
    lines.append(
        "⚠️  DISCLAIMER: Research decision-support tool only. "
        "Not medical advice. Requires oncologist validation."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _priority_label_to_confidence(label: str) -> float:
    """Map Apollo priority label to numeric confidence."""
    return {
        "resistance_match":   0.95,
        "cns_disease":        0.93,
        "driver_mutation":    0.90,
        "urgency":            0.80,
        "io_preference":      0.85,
        "first_safe_option":  0.70,
    }.get(label, 0.70)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_phase6(patient: dict, journey_id: str = None, storage_backend=None) -> str:
    """
    Full Phase 6 pipeline.

    Accepts EITHER:
      Phase 6A schema: disease, biomarkers (bool-keyed), organ_function, ...
      Phase 5 schema:  cancer_type, biomarkers (str-keyed EGFR/ALK), creatinine_clearance, ...

    PHASE 10: Accepts optional journey_id to integrate PatientJourney persistence.
      journey_id: str — if provided, loads journey and auto-populates prior_therapies.
      storage_backend: StorageBackend instance — defaults to JSONStorageBackend.

    Returns:
        Formatted multi-section output string.
    """
    # ── PHASE 10: PatientJourney integration (Issue 4) ──────────────────────
    if journey_id:
        try:
            from patient_journey import PatientJourney, JSONStorageBackend, integrate_journey_into_pipeline
            _backend = storage_backend or JSONStorageBackend()
            journey = PatientJourney.load(journey_id, _backend)
            if journey:
                patient = integrate_journey_into_pipeline(patient, journey)
                patient["_journey_prior_therapies"] = journey.get_prior_therapies()
        except Exception as _journey_exc:
            import logging
            logging.getLogger(__name__).warning("PatientJourney load failed: %s", _journey_exc)
    # ── Phase 9: Clinical guardrail gate (runs on raw patient before normalisation) ──
    guardrail_result = _CONSTRAINT.validate_case(patient)
    if guardrail_result["blocked"]:
        reasons  = "\n".join(f"  • {r}" for r in guardrail_result["reason"])
        actions  = "\n".join(f"  • {a}" for a in guardrail_result["required_actions"])
        warnings = "\n".join(f"  • {w}" for w in guardrail_result["warnings"])
        disclaimer = (
            "\n⚠️  DISCLAIMER: Research decision-support tool only. "
            "Not medical advice. Requires oncologist validation."
        )
        return (
            "## CLINICAL GUARDRAIL — BLOCKED\n"
            f"{reasons}\n\n"
            "## REQUIRED ACTIONS\n"
            f"{actions}\n\n"
            + (f"## WARNINGS\n{warnings}\n" if guardrail_result["warnings"] else "")
            + disclaimer
        )

    # ── Normalise patient to Phase 6A format ─────────────────────────────────
    p6a = _normalise_patient(patient)

    # Attach guardrail result so it flows through to final output
    p6a["_guardrail"] = guardrail_result

    # ── Phase 9: Uncertainty Mapper — runs BEFORE intent engine ──────────────
    # Uncertainty must be mapped before intent so intent confidence can factor
    # in what data is missing. Result is injected into patient context so
    # downstream layers can read it, and attached to final output.
    uncertainty = UNCERTAINTY_MAPPER.map_uncertainty(patient)
    p6a["uncertainty"] = uncertainty

    # ── Phase 9: Patient Intent Engine — determine intent ────────────────────
    # Runs on raw patient dict (before normalisation) so it reads treatment_goal,
    # frailty_score, social_support directly as supplied. ECOG is read here for
    # intent level only — constraint engine already used it for option gating.
    intent_data         = INTENT_ENGINE.determine_intent(patient)
    p6a["intent"]       = intent_data["intent"]
    p6a["intent_data"]  = intent_data

    # ── Phase 6A: Policy layer → option universe ──────────────────────────────
    policy_result  = _POLICY.get_options(p6a)
    policy_options = policy_result.get("options", [])

    # ── Phase 6A: Constraint layer → safety filter ────────────────────────────
    constraint_result = _CONSTRAINT.filter(p6a, policy_options)
    safe_6a           = constraint_result.get("safe_options", [])

    # ── LUNG_TREATMENTS eligibility (for HybridEngine + JustificationEngine) ──
    safe_options, rejected = _build_safe_options(p6a)

    if not safe_options:
        return (
            "## HYBRID DECISION\n  NO_PATH — No treatment options passed eligibility gating.\n\n"
            "## SAFETY WARNINGS\n" +
            "\n".join(f"  • {r['rejection_reason']}" for r in rejected) +
            "\n\n⚠️  DISCLAIMER: Research decision-support tool only. "
            "Not medical advice. Requires oncologist validation."
        )

    # ── Phase 6B: Apollo Mode (uses Phase 6A safe options if available) ───────
    apollo_safe = safe_6a if safe_6a else safe_options
    apollo_raw  = _APOLLO.decide(apollo_safe, p6a)
    apollo_out  = {
        "final_regimen": apollo_raw.get("choice", ""),
        "line":          1,
        "confidence":    _priority_label_to_confidence(apollo_raw.get("priority_used", "")),
        "mode":          "apollo",
        "reason":        apollo_raw.get("reason", ""),
    }

    # ── Phase 6B: Manhattan Mode ──────────────────────────────────────────────
    manhattan_safe   = safe_6a if safe_6a else safe_options
    manhattan_ranked = _MANHATTAN.evaluate(manhattan_safe, p6a)
    manhattan_out: dict = {}
    if manhattan_ranked:
        top = manhattan_ranked[0]
        manhattan_out = {
            "final_regimen": top.get("regimen", ""),
            "line":          1,
            "confidence":    0.82,
            "mode":          "manhattan",
        }

    # ── Phase 6C: Hybrid Engine ───────────────────────────────────────────────
    hybrid     = HybridEngine()
    hybrid_out = hybrid.select(
        apollo_output    = apollo_out,
        manhattan_output = manhattan_out,
        safe_options     = safe_options,
        patient_context  = p6a.get("_raw", patient),
    )

    # ── Phase 6C: Justification Engine ───────────────────────────────────────
    je = JustificationEngine()
    justification = je.generate(
        all_options      = safe_options,
        rejected_options = rejected,
        final_selection  = hybrid_out,
        hybrid_debug     = hybrid_out.get("_debug", {}),
        patient_context  = p6a.get("_raw", patient),
    )

    # ── Phase 9: Apply intent modulation to decision output ───────────────────
    hybrid_out = INTENT_ENGINE.apply_intent_modulation(hybrid_out, intent_data)

    # ── Phase 9: Quant Layer — risk profile ──────────────────────────────────
    # Runs on the raw patient dict to read ef, egfr, age, ecog directly.
    # Injected AFTER decision so it annotates output without influencing selection.
    risk_profile = QUANT_LAYER.build_risk_profile(patient)

    # ── Phase 9: Failure Simulator — LAST layer ───────────────────────────────
    # Reads from quant layer (risk_profile) and uncertainty mapper output.
    # Never reads raw patient fields directly — stays consistent with upstream
    # risk scores. Runs after everything else so it sees the full picture.
    failure_simulation = FAILURE_SIMULATOR.simulate(
        patient      = patient,
        hybrid_out   = hybrid_out,
        risk_profile = risk_profile,
        uncertainty  = uncertainty,
    )

    # ── Policy space (all options, selected + rejected) ───────────────────────
    policy_space = safe_options + [{"name": r["treatment_name"]} for r in rejected]

    return _format_output(
        apollo_out         = apollo_out,
        manhattan_out      = manhattan_ranked if manhattan_ranked else manhattan_out,
        hybrid_out         = hybrid_out,
        justification      = justification,
        policy_space       = policy_space,
        risk_profile       = risk_profile,
        uncertainty        = uncertainty,
        guardrail          = guardrail_result,
        failure_simulation = failure_simulation,
    )


# Expose internal helpers for test suite backward compatibility
_run_apollo_mode    = None   # replaced by ApolloMode — tests should use _APOLLO.decide()
_run_manhattan_mode = None   # replaced by ManhattanMode — tests should use _MANHATTAN.evaluate()
