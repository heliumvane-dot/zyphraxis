"""
clinical/constraint_engine.py — Constraint Engine (Phase 6A + Phase 9 extension)

Position in pipeline:
    PolicyEngine.get_options()  →  ConstraintEngine.filter()
                                →  [Apollo | Manhattan | Hybrid — Phase 6B+]

Phase 6A constraints (unchanged):
    Renal severe      → remove cisplatin-containing regimens
    Hepatic severe    → flag TKI caution
    Marrow suppressed → avoid all chemo-containing regimens
    Brain mets        → tag CNS-active therapies; flag non-CNS-active

Phase 9 additions — clinical guardrails per cancer type:
    validate_case(patient) → runs BEFORE the pipeline begins.
    Returns:
        {
            "blocked":          bool,
            "reason":           [str],        # hard stop messages
            "warnings":         [str],        # cautions, not blocks
            "required_actions": [str],        # what clinician must do
        }

    Guardrail logic per cancer type:
        Lung (stage III/IV)  : requires molecular profiling (EGFR/ALK/PD-L1)
        Breast               : requires ER status + HER2 status (hard blocks)
        Pancreatic (III/IV)  : BRCA warning + resectability warning
        Prostate             : PSA + Gleason score warning
        Colorectal           : MSI/MMR status warning
        All cancers          : hard organ blocks — EF < 35 or eGFR < 20

    Design principle:
        Block rarely. Warn often.
        Over-blocking → system becomes useless.
        Under-blocking → system becomes dangerous.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constraint severity constants
# ---------------------------------------------------------------------------

ORGAN_SEVERE      = "severe"
ORGAN_MODERATE    = "moderate"
MARROW_SUPPRESSED = "suppressed"
BURDEN_HIGH       = "high"

# Phase 9 hard-stop organ thresholds
EF_HARD_BLOCK   = 35   # ejection fraction below this = no cardiotoxic therapy
EGFR_HARD_BLOCK = 20   # eGFR below this = no nephrotoxic therapy


# ---------------------------------------------------------------------------
# Phase 9 — validate_case  (runs before pipeline)
# ---------------------------------------------------------------------------

def validate_case(patient: dict) -> Dict[str, Any]:
    """
    Phase 9 clinical guardrail check.

    Call this BEFORE run_phase6() begins. If result["blocked"] is True,
    return it immediately without running the decision pipeline.

    Args:
        patient: Raw or normalised patient dict. Works with Phase 5 and Phase 6A schemas.

    Returns:
        {
            "blocked":          bool,
            "reason":           [str],
            "warnings":         [str],
            "required_actions": [str],
        }
    """
    errors:   List[str] = []
    warnings: List[str] = []
    actions:  List[str] = []

    cancer = (
        patient.get("cancer")
        or patient.get("cancer_type")
        or patient.get("disease")
        or ""
    ).lower()

    stage     = (patient.get("stage") or "").upper()
    mutations = patient.get("mutations") or patient.get("biomarkers") or {}
    ef        = patient.get("ef")
    egfr_val  = patient.get("egfr")   # kidney eGFR — distinct from EGFR mutation

    # 1. Universal hard organ stops
    if ef is not None and ef < EF_HARD_BLOCK:
        errors.append(
            f"Severely reduced cardiac function (EF {ef}% < {EF_HARD_BLOCK}%). "
            "Cardiotoxic therapy contraindicated until cardiac review."
        )
        actions.append("Urgent cardiology review before any systemic therapy")

    if egfr_val is not None and egfr_val < EGFR_HARD_BLOCK:
        errors.append(
            f"Severe renal impairment (eGFR {egfr_val} mL/min < {EGFR_HARD_BLOCK}). "
            "Nephrotoxic agents (cisplatin, high-dose methotrexate) contraindicated."
        )
        actions.append("Nephrology consult before systemic therapy")

    # 2. Cancer-specific guardrails
    if cancer == "lung":
        _guard_lung(patient, stage, mutations, errors, warnings, actions)
    elif cancer in ("breast", "breast cancer"):
        _guard_breast(patient, errors, warnings, actions)
    elif cancer in ("pancreatic", "pancreas", "pancreatic cancer"):
        _guard_pancreatic(patient, stage, mutations, warnings, actions)
    elif cancer in ("prostate", "prostate cancer"):
        _guard_prostate(patient, warnings, actions)
    elif cancer in ("colorectal", "colon", "rectal", "colorectal cancer"):
        _guard_colorectal(patient, warnings, actions)

    # 3. Organ function warnings (non-blocking, above hard-stop thresholds)
    _warn_organ_function(ef, egfr_val, warnings)

    blocked = len(errors) > 0

    if blocked:
        logger.warning(
            "ClinicalGuardrail BLOCKED — cancer=%s stage=%s reasons=%d",
            cancer, stage, len(errors)
        )
    else:
        logger.info(
            "ClinicalGuardrail PASSED — cancer=%s stage=%s warnings=%d",
            cancer, stage, len(warnings)
        )

    return {
        "blocked":          blocked,
        "reason":           errors,
        "warnings":         warnings,
        "required_actions": actions,
    }


# ---------------------------------------------------------------------------
# Cancer-specific guardrail helpers
# ---------------------------------------------------------------------------

def _guard_lung(patient, stage, mutations, errors, warnings, actions):
    """Lung: requires molecular profiling at stage III/IV."""
    adv_stages = ("III", "IV", "IIIA", "IIIB", "IIIC", "IVA", "IVB")
    if stage not in adv_stages:
        return

    if isinstance(mutations, dict):
        has_egfr = bool(mutations.get("EGFR") or mutations.get("egfr_mutation"))
        has_alk  = bool(mutations.get("ALK")  or mutations.get("alk_rearrangement"))
        has_ros1 = bool(mutations.get("ROS1") or mutations.get("ros1_fusion"))
        pdl1     = mutations.get("PD-L1") or mutations.get("pd_l1") or mutations.get("pdl1")
    elif isinstance(mutations, list):
        has_egfr = any("EGFR" in str(m).upper() for m in mutations)
        has_alk  = any("ALK"  in str(m).upper() for m in mutations)
        has_ros1 = any("ROS1" in str(m).upper() for m in mutations)
        pdl1     = patient.get("pdl1")
    else:
        has_egfr = has_alk = has_ros1 = False
        pdl1 = patient.get("pdl1")

    profiling_done = has_egfr or has_alk or has_ros1 or (pdl1 is not None)

    if not profiling_done:
        errors.append(
            f"Stage {stage} NSCLC requires molecular profiling before treatment selection. "
            "EGFR, ALK, ROS1, and PD-L1 status must be confirmed."
        )
        actions.append(
            "Order comprehensive molecular profiling: EGFR/ALK/ROS1/KRAS/BRAF/PD-L1"
        )
    else:
        if not has_egfr and not has_alk and not has_ros1:
            warnings.append(
                "No actionable driver mutation detected. "
                "Confirm EGFR/ALK/ROS1 negative before defaulting to IO/chemo pathway."
            )


def _guard_breast(patient, errors, warnings, actions):
    """Breast: ER and HER2 status are hard requirements."""
    er_status   = patient.get("er_status")
    her2_status = patient.get("her2_status")

    if er_status is None:
        errors.append(
            "ER (oestrogen receptor) status not confirmed. "
            "Cannot determine hormone receptor pathway or endocrine therapy eligibility."
        )
        actions.append("Order ER/PR immunohistochemistry (IHC)")

    if her2_status is None:
        errors.append(
            "HER2 status not confirmed. "
            "Cannot determine anti-HER2 therapy eligibility (trastuzumab, pertuzumab, T-DM1)."
        )
        actions.append("Order HER2 IHC; if 2+, confirm with FISH/ISH")

    # BRCA recommendation for TNBC
    er_neg   = str(er_status).lower()   in ("negative", "neg", "0", "false") if er_status else False
    her2_neg = str(her2_status).lower() in ("negative", "neg", "0", "false") if her2_status else False
    if er_neg and her2_neg:
        brca = patient.get("brca1") or patient.get("brca2") or patient.get("brca")
        if brca is None:
            warnings.append(
                "Triple-negative breast cancer (TNBC) pattern detected. "
                "BRCA1/2 germline testing recommended for PARP inhibitor eligibility."
            )
            actions.append("Order BRCA1/2 germline testing")


def _guard_pancreatic(patient, stage, mutations, warnings, actions):
    """Pancreatic: BRCA warning + resectability needed for surgery decision."""
    if stage in ("III", "IV"):
        if isinstance(mutations, dict):
            has_brca = any(
                "BRCA" in str(k).upper() or "BRCA" in str(v).upper()
                for k, v in mutations.items()
            )
        elif isinstance(mutations, list):
            has_brca = any("BRCA" in str(m).upper() for m in mutations)
        else:
            has_brca = False

        if not has_brca:
            warnings.append(
                f"Stage {stage} pancreatic cancer: BRCA1/2 mutation status not confirmed. "
                "PARP inhibitor eligibility (olaparib maintenance) requires germline testing."
            )
            actions.append("Consider germline BRCA1/2 testing for PARP inhibitor eligibility")

    if "resectability" not in patient:
        warnings.append(
            "Surgical resectability status not documented. "
            "Resectability determines treatment intent (surgery vs definitive chemo/RT)."
        )
        actions.append("Multidisciplinary surgical evaluation for resectability assessment")


def _guard_prostate(patient, warnings, actions):
    """Prostate: PSA + Gleason/ISUP grade needed for risk stratification."""
    if patient.get("psa") is None:
        warnings.append(
            "PSA value not provided. Required for risk stratification "
            "(low/intermediate/high/very-high risk grouping)."
        )
        actions.append("Document baseline PSA")

    if patient.get("gleason_score") is None and patient.get("isup_grade") is None:
        warnings.append(
            "Gleason score / ISUP grade not documented. "
            "Required for risk group classification and treatment selection."
        )
        actions.append("Confirm Gleason score from biopsy pathology report")


def _guard_colorectal(patient, warnings, actions):
    """Colorectal: MSI/MMR status essential for IO eligibility."""
    msi = (
        patient.get("msi_status")
        or patient.get("msi")
        or patient.get("mmr_status")
    )
    if msi is None:
        warnings.append(
            "MSI/MMR status not confirmed. "
            "MSI-H/dMMR tumours are eligible for pembrolizumab (KEYNOTE-177). "
            "This cannot be assessed without testing."
        )
        actions.append("Order MSI PCR or MMR IHC (MLH1, MSH2, MSH6, PMS2)")

    mutations = patient.get("mutations") or []
    kras = patient.get("kras") or (
        "KRAS" in str(mutations).upper() if mutations else None
    )
    if kras is None:
        warnings.append(
            "KRAS/NRAS/BRAF mutation status not documented. "
            "Required for anti-EGFR therapy eligibility (cetuximab, panitumumab)."
        )
        actions.append("Order extended RAS/BRAF panel")


def _warn_organ_function(ef, egfr_val, warnings):
    """Non-blocking organ function warnings (above hard-stop thresholds)."""
    if ef is not None:
        if EF_HARD_BLOCK <= ef < 45:
            warnings.append(
                f"Reduced cardiac function (EF {ef}%). "
                "Cardiotoxic agents (anthracyclines, trastuzumab) require enhanced monitoring."
            )
        elif 45 <= ef < 50:
            warnings.append(
                f"Mildly reduced ejection fraction (EF {ef}%). "
                "Baseline cardiac monitoring recommended before anthracycline therapy."
            )

    if egfr_val is not None:
        if EGFR_HARD_BLOCK <= egfr_val < 30:
            warnings.append(
                f"Severe renal impairment (eGFR {egfr_val}). "
                "Cisplatin contraindicated. Carboplatin with dose reduction if platinum required."
            )
        elif 30 <= egfr_val < 60:
            warnings.append(
                f"Moderate renal impairment (eGFR {egfr_val}). "
                "Review dosing for renally-cleared agents."
            )


# ---------------------------------------------------------------------------
# Patient model helper (Phase 6A — unchanged)
# ---------------------------------------------------------------------------

def _extract_patient_fields(patient: dict) -> dict:
    organ = patient.get("organ_function") or {}
    return {
        "ecog":                   patient.get("ecog"),
        "renal":                  (organ.get("renal") or "").lower(),
        "hepatic":                (organ.get("hepatic") or "").lower(),
        "marrow_status":          (patient.get("marrow_status") or "").lower(),
        "brain_mets":             bool(patient.get("brain_mets", False)),
        "brain_mets_symptomatic": bool(patient.get("brain_mets_symptomatic", False)),
        "disease_burden":         (patient.get("disease_burden") or "").lower(),
    }


# ---------------------------------------------------------------------------
# Individual constraint checkers (Phase 6A — unchanged)
# ---------------------------------------------------------------------------

def _check_renal(option: dict, fields: dict) -> tuple[bool, List[str]]:
    if fields["renal"] != ORGAN_SEVERE:
        return False, []
    tags = option.get("tags", {})
    contains_cisplatin = tags.get("contains_cisplatin", False)
    regimen_lower = option.get("regimen", "").lower()
    if contains_cisplatin or "cisplatin" in regimen_lower:
        return True, [
            "Cisplatin contraindicated: severe renal impairment (CrCl likely <45 mL/min). "
            "Carboplatin-based substitution required if platinum therapy is indicated."
        ]
    return False, []


def _check_hepatic(option: dict, fields: dict) -> tuple[bool, List[str]]:
    if fields["hepatic"] != ORGAN_SEVERE:
        return False, []
    tags = option.get("tags", {})
    driver_type = tags.get("driver_type", "NONE")
    is_tki = driver_type in ("EGFR", "ALK", "ROS1")
    if is_tki:
        return False, [
            f"TKI caution: severe hepatic impairment. {option.get('regimen', 'This regimen')} "
            "is hepatically metabolised (CYP3A4). Dose reduction or alternative required. "
            "Discuss with hepatology before prescribing."
        ]
    return False, []


def _check_marrow(option: dict, fields: dict) -> tuple[bool, List[str]]:
    if fields["marrow_status"] != MARROW_SUPPRESSED:
        return False, []
    tags = option.get("tags", {})
    if tags.get("chemo", False):
        return True, [
            "Chemotherapy blocked: bone marrow suppression detected. "
            "Haematological reserve insufficient for cytotoxic therapy. "
            "Re-evaluate after marrow recovery or consider non-chemo alternatives."
        ]
    return False, []


def _check_brain_mets(option: dict, fields: dict) -> tuple[bool, List[str]]:
    if not fields["brain_mets"]:
        return False, []
    tags = option.get("tags", {})
    cns_active = tags.get("CNS_active", False)
    if not cns_active:
        severity = "symptomatic " if fields["brain_mets_symptomatic"] else ""
        return False, [
            f"Brain metastases present ({severity}). "
            f"{option.get('regimen', 'This regimen')} has limited CNS penetration. "
            "Consider CNS-active alternative (e.g. Osimertinib, Alectinib, Lorlatinib) "
            "if driver mutation present, or local CNS therapy (SRS/WBRT)."
        ]
    return False, []


def _build_priority_tags(option: dict, fields: dict) -> List[str]:
    tags  = option.get("tags", {})
    ptags: List[str] = []
    if fields["brain_mets"] and tags.get("CNS_active", False):
        ptags.append("cns_coverage")
    driver_type = tags.get("driver_type", "NONE")
    if driver_type != "NONE":
        ptags.append(f"driver_matched_{driver_type.lower()}")
    if fields["disease_burden"] == BURDEN_HIGH:
        if tags.get("IO") or driver_type != "NONE":
            ptags.append("fast_response")
    return ptags


# ---------------------------------------------------------------------------
# ConstraintEngine
# ---------------------------------------------------------------------------

class ConstraintEngine:
    """
    Phase 6A + Phase 9: Safety filtering layer.

    Phase 6A: filter(patient, policy_options) — per-treatment option filtering.
    Phase 9:  validate_case(patient)          — pre-pipeline patient gate.
    """

    _CONSTRAINT_CHECKERS = [
        _check_renal,
        _check_hepatic,
        _check_marrow,
        _check_brain_mets,
    ]

    def validate_case(self, patient: dict) -> Dict[str, Any]:
        """Phase 9 guardrail. Delegates to module-level validate_case()."""
        return validate_case(patient)

    def filter(
        self,
        patient: dict,
        policy_options: List[dict],
    ) -> Dict[str, Any]:
        engine_warnings: List[str] = []

        if not policy_options:
            engine_warnings.append(
                "ConstraintEngine received empty option list from PolicyEngine. "
                "No constraint filtering possible — review PolicyEngine output."
            )
            return self._empty_result(engine_warnings)

        fields        = _extract_patient_fields(patient)
        all_annotated: List[dict] = []

        for opt in policy_options:
            annotated = self._annotate_option(opt, fields)
            all_annotated.append(annotated)

        safe    = [o for o in all_annotated if o["allowed"]]
        blocked = [o for o in all_annotated if not o["allowed"]]

        if not safe:
            engine_warnings.append(
                "All policy options were blocked by clinical constraints. "
                "No guideline-safe treatment pathway available with current patient parameters. "
                "Clinical review required."
            )

        logger.info(
            "ConstraintEngine: total=%d safe=%d blocked=%d",
            len(all_annotated), len(safe), len(blocked)
        )

        return {
            "safe_options":    safe,
            "blocked_options": blocked,
            "all_options":     all_annotated,
            "warnings":        engine_warnings,
        }

    def _annotate_option(self, option: dict, fields: dict) -> dict:
        annotated     = dict(option)
        all_warnings: List[str] = []
        is_blocked    = False

        for checker in self._CONSTRAINT_CHECKERS:
            blocked, warns = checker(option, fields)
            all_warnings.extend(warns)
            if blocked:
                is_blocked = True

        priority_tags = _build_priority_tags(option, fields)
        annotated["allowed"]       = not is_blocked
        annotated["warnings"]      = all_warnings
        annotated["priority_tags"] = priority_tags
        return annotated

    @staticmethod
    def _empty_result(warnings: List[str]) -> dict:
        return {
            "safe_options":    [],
            "blocked_options": [],
            "all_options":     [],
            "warnings":        warnings,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

CONSTRAINT_ENGINE = ConstraintEngine()
