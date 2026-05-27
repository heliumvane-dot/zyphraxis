"""
engine/uncertainty_mapper.py — Uncertainty Mapper (Phase 9, Step 4)

Position in pipeline:
    Guardrail (Step 1)
        → map_uncertainty()     ← runs BEFORE intent engine
        → Intent Engine (Step 3)  ← can read case["uncertainty"]
        → Decision Engine
        → Intent Modulation
        → Quant Layer (Step 2)
        → [Failure Simulator — Step 5]

What this layer does:
    Detects missing or ambiguous clinical data, classifies each gap by
    severity, suggests the next diagnostic action, and computes a
    confidence penalty that will be consumed by the Failure Simulator
    (Step 5) to weight failure probabilities.

    "Doctors don't trust systems that say 'I know everything'.
     They trust systems that say 'here's what I know, here's what I don't,
     and here's what to do next.'"

Uncertainty tiers:
    CRITICAL   — decision cannot be made safely without this data
    MODERATE   — important for refinement; decision possible but suboptimal
    MINOR      — useful context; absence doesn't materially affect selection

Confidence penalty scoring:
    Each critical gap  = -30 pts
    Each moderate gap  = -15 pts
    Each minor gap     =  -5 pts

    >= 60 pts → High penalty   (≥60% confidence reduction)
    >= 30 pts → Moderate penalty (30–60%)
    >   0 pts → Low penalty    (<30%)
    == 0 pts  → None

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Penalty weights
# ---------------------------------------------------------------------------

_PENALTY = {"critical": 30, "moderate": 15, "minor": 5}


# ---------------------------------------------------------------------------
# UncertaintyMapper
# ---------------------------------------------------------------------------

class UncertaintyMapper:
    """
    Phase 9 uncertainty mapper.

    Usage in pipeline:
        uncertainty = UNCERTAINTY_MAPPER.map_uncertainty(patient)
        patient["uncertainty"] = uncertainty        # inject into case
        ...
        decision_output["uncertainty"] = uncertainty  # attach to output
    """

    def map_uncertainty(self, patient: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect and classify missing clinical data.

        Args:
            patient: Raw patient dict (same schema accepted by run_phase6).

        Returns:
            {
                "missing_critical":      [str],
                "missing_moderate":      [str],
                "missing_minor":         [str],
                "recommended_actions":   [str],
                "confidence_penalty":    str,   — human-readable label
                "penalty_score":         int,   — raw score (for Step 5)
                "uncertainty_summary":   str,   — one-line human summary
            }
        """
        critical: List[str] = []
        moderate: List[str] = []
        minor:    List[str] = []
        actions:  List[str] = []

        cancer = (
            patient.get("cancer")
            or patient.get("cancer_type")
            or patient.get("disease")
            or ""
        ).lower()

        stage     = (patient.get("stage") or "").upper()
        mutations = patient.get("mutations") or patient.get("biomarkers") or {}

        # ── Universal checks (all cancers) ───────────────────────────────
        self._check_universal(patient, cancer, stage, critical, moderate, minor, actions)

        # ── Cancer-specific checks ────────────────────────────────────────
        if cancer == "lung":
            self._check_lung(patient, stage, mutations, critical, moderate, minor, actions)
        elif cancer in ("breast", "breast cancer"):
            self._check_breast(patient, mutations, critical, moderate, minor, actions)
        elif cancer in ("pancreatic", "pancreas", "pancreatic cancer"):
            self._check_pancreatic(patient, stage, mutations, moderate, minor, actions)
        elif cancer in ("prostate", "prostate cancer"):
            self._check_prostate(patient, moderate, minor, actions)
        elif cancer in ("colorectal", "colon", "rectal", "colorectal cancer"):
            self._check_colorectal(patient, mutations, moderate, minor, actions)

        # ── Organ function checks ─────────────────────────────────────────
        self._check_organ_function(patient, moderate, minor, actions)

        # ── Penalty ───────────────────────────────────────────────────────
        score = (
            len(critical) * _PENALTY["critical"] +
            len(moderate) * _PENALTY["moderate"] +
            len(minor)    * _PENALTY["minor"]
        )
        penalty_label = self._penalty_label(score)

        # ── Summary ───────────────────────────────────────────────────────
        total = len(critical) + len(moderate) + len(minor)
        if total == 0:
            summary = "No missing data detected — high-confidence inputs"
        elif len(critical) > 0:
            summary = (
                f"{len(critical)} critical gap(s) detected — "
                "decision reliability significantly reduced until resolved"
            )
        else:
            summary = (
                f"{len(moderate)} moderate gap(s) and {len(minor)} minor gap(s) — "
                "decision possible, refinement recommended"
            )

        result = {
            "missing_critical":    critical,
            "missing_moderate":    moderate,
            "missing_minor":       minor,
            "recommended_actions": actions,
            "confidence_penalty":  penalty_label,
            "penalty_score":       score,
            "uncertainty_summary": summary,
        }

        logger.info(
            "UncertaintyMapper: critical=%d moderate=%d minor=%d penalty=%s",
            len(critical), len(moderate), len(minor), penalty_label
        )

        return result

    # ── Universal gaps (all cancer types) ────────────────────────────────────

    def _check_universal(self, patient, cancer, stage, critical, moderate, minor, actions):
        if not stage:
            critical.append("Cancer stage not documented")
            actions.append("Confirm staging with imaging and pathology")

        if not cancer:
            critical.append("Cancer type not specified")
            actions.append("Confirm primary tumour site and histology")

        if patient.get("ecog") is None:
            moderate.append("ECOG performance status not recorded")
            actions.append("Assess and document ECOG performance status")

        if patient.get("age") is None:
            minor.append("Patient age not provided")

    # ── Lung-specific gaps ────────────────────────────────────────────────────

    def _check_lung(self, patient, stage, mutations, critical, moderate, minor, actions):
        adv = ("III", "IV", "IIIA", "IIIB", "IIIC", "IVA", "IVB")
        if stage not in adv:
            return

        # Molecular profiling — critical at stage III/IV
        if isinstance(mutations, dict):
            has_egfr = bool(mutations.get("EGFR") or mutations.get("egfr_mutation"))
            has_alk  = bool(mutations.get("ALK")  or mutations.get("alk_rearrangement"))
            has_ros1 = bool(mutations.get("ROS1"))
            pdl1     = mutations.get("PD-L1") or mutations.get("pdl1") or patient.get("pdl1")
        elif isinstance(mutations, list):
            has_egfr = any("EGFR" in str(m).upper() for m in mutations)
            has_alk  = any("ALK"  in str(m).upper() for m in mutations)
            has_ros1 = any("ROS1" in str(m).upper() for m in mutations)
            pdl1     = patient.get("pdl1")
        else:
            has_egfr = has_alk = has_ros1 = False
            pdl1 = patient.get("pdl1")

        if not (has_egfr or has_alk or has_ros1):
            critical.append("EGFR/ALK/ROS1 mutation status not confirmed")
            actions.append("Order comprehensive molecular panel: EGFR/ALK/ROS1/KRAS/BRAF")

        if pdl1 is None:
            critical.append("PD-L1 expression level (TPS%) not documented")
            actions.append("Order PD-L1 IHC (22C3 assay or equivalent)")

        # Brain met status
        if patient.get("brain_mets") is None:
            moderate.append("Brain metastasis status unknown")
            actions.append("Consider brain MRI for stage IV NSCLC staging")

        # Histology
        if not patient.get("histology") and not patient.get("subtype"):
            moderate.append("Lung cancer histology not specified (adenocarcinoma vs SCC vs other)")
            actions.append("Confirm histology from biopsy pathology report")

    # ── Breast-specific gaps ──────────────────────────────────────────────────

    def _check_breast(self, patient, mutations, critical, moderate, minor, actions):
        # ER/HER2 would already be a guardrail block — flag as moderate
        # here only if somehow they passed (legacy data, edge case)
        if patient.get("er_status") is None:
            moderate.append("ER status not confirmed (should have been blocked by guardrail)")

        if patient.get("her2_status") is None:
            moderate.append("HER2 status not confirmed (should have been blocked by guardrail)")

        if patient.get("ki67") is None:
            minor.append("Ki-67 proliferation index not documented")

        if patient.get("grade") is None:
            minor.append("Tumour grade (I/II/III) not documented")

        # BRCA for TNBC
        er_neg   = str(patient.get("er_status", "")).lower()   in ("negative", "neg", "0", "false")
        her2_neg = str(patient.get("her2_status", "")).lower() in ("negative", "neg", "0", "false")
        if er_neg and her2_neg:
            brca = patient.get("brca1") or patient.get("brca2") or patient.get("brca")
            if brca is None:
                moderate.append("BRCA1/2 status unknown in TNBC setting")
                actions.append("Order germline BRCA1/2 testing — PARP inhibitor eligibility")

    # ── Pancreatic-specific gaps ──────────────────────────────────────────────

    def _check_pancreatic(self, patient, stage, mutations, moderate, minor, actions):
        if stage in ("III", "IV"):
            if isinstance(mutations, dict):
                has_brca = any("BRCA" in str(k).upper() for k in mutations)
            elif isinstance(mutations, list):
                has_brca = any("BRCA" in str(m).upper() for m in mutations)
            else:
                has_brca = False

            if not has_brca:
                moderate.append("BRCA1/2 germline status not confirmed")
                actions.append("Germline BRCA1/2 testing — olaparib maintenance eligibility")

        if "resectability" not in patient:
            moderate.append("Surgical resectability status not documented")
            actions.append("Multidisciplinary surgical evaluation required")

        if patient.get("ca19_9") is None:
            minor.append("CA 19-9 tumour marker not recorded")

    # ── Prostate-specific gaps ────────────────────────────────────────────────

    def _check_prostate(self, patient, moderate, minor, actions):
        if patient.get("psa") is None:
            moderate.append("PSA level not documented")
            actions.append("Record baseline PSA for risk stratification")

        if patient.get("gleason_score") is None and patient.get("isup_grade") is None:
            moderate.append("Gleason score / ISUP grade not confirmed")
            actions.append("Confirm Gleason from biopsy pathology report")

        if patient.get("castration_status") is None:
            moderate.append("Castration-sensitive vs castration-resistant status unknown")
            actions.append("Confirm testosterone level and castration status")

        if patient.get("bone_mets") is None:
            minor.append("Bone metastasis status not documented")

    # ── Colorectal-specific gaps ──────────────────────────────────────────────

    def _check_colorectal(self, patient, mutations, moderate, minor, actions):
        msi = (
            patient.get("msi_status")
            or patient.get("msi")
            or patient.get("mmr_status")
        )
        if msi is None:
            moderate.append("MSI/MMR status not confirmed")
            actions.append("Order MSI PCR or MMR IHC (MLH1, MSH2, MSH6, PMS2)")

        kras = patient.get("kras") or (
            "KRAS" in str(mutations).upper() if mutations else False
        )
        if not kras:
            moderate.append("RAS/BRAF mutation status not documented")
            actions.append("Order extended RAS/BRAF panel — anti-EGFR eligibility")

        if patient.get("sidedness") is None:
            minor.append("Primary tumour sidedness (left vs right colon) not documented")

    # ── Organ function gaps (all cancers) ─────────────────────────────────────

    def _check_organ_function(self, patient, moderate, minor, actions):
        if patient.get("ef") is None:
            minor.append("Cardiac ejection fraction (EF) not provided")

        if patient.get("egfr") is None:
            moderate.append("Renal function (eGFR) not documented")
            actions.append("Record eGFR / creatinine for nephrotoxic agent dosing")

        if patient.get("liver_function") is None and patient.get("bilirubin") is None:
            minor.append("Liver function (bilirubin / LFTs) not documented")

    # ── Penalty helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _penalty_label(score: int) -> str:
        if score >= 60:
            return "High (≥60% confidence reduction)"
        elif score >= 30:
            return "Moderate (30–60% confidence reduction)"
        elif score > 0:
            return "Low (<30% confidence reduction)"
        return "None"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

UNCERTAINTY_MAPPER = UncertaintyMapper()
