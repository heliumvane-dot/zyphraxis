"""
clinical/policy_engine.py — Policy Engine (Phase 6A)

Position in Phase 6 pipeline:
    Patient Input  →  PolicyEngine.get_options()  →  ConstraintEngine.filter()
                   →  [Apollo | Manhattan | Hybrid — Phase 6B+]

What it does:
    Reads the `policy` section of clinical/pathways.yaml.
    For a given patient profile, returns every guideline-sanctioned regimen
    for the cancer type and line of therapy — UNFILTERED by patient safety.
    Safety filtering happens exclusively in ConstraintEngine.

    Output per option:
        {
            "regimen":   str,
            "line":      "first-line" | "progression",
            "evidence":  str,
            "tags": {
                "driver_type": "EGFR" | "ALK" | "ROS1" | "NONE",
                "IO":          bool,
                "chemo":       bool,
                "CNS_active":  bool,          # only present when true
                "contains_cisplatin": bool,   # only present when true
            }
        }

What it does NOT do:
    - Apply patient organ-function constraints  (→ ConstraintEngine)
    - Call DecisionAggregator                  (→ Phase 6B+)
    - Write to audit log directly
    - Return empty list without a warning

Backward compatibility:
    PathwayEngine (Phase 5) reads the `pathways` section — unchanged.
    PolicyEngine reads the NEW `policy` section — no conflict.

Schema validation:
    PolicyConfigSchema validates the `policy` section at startup.
    Any malformed YAML raises ValidationError before the first request.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

PATHWAYS_YAML_PATH = Path(__file__).parent / "pathways.yaml"


# ---------------------------------------------------------------------------
# Pydantic schema — validated at startup
# ---------------------------------------------------------------------------

class TagSchema(BaseModel):
    """
    Required tags on every policy option.
    driver_type is always present; others default appropriately.
    """
    driver_type:        str  = Field(..., description="EGFR | ALK | ROS1 | NONE")
    IO:                 bool = Field(False)
    chemo:              bool = Field(False)
    CNS_active:         bool = Field(False)
    contains_cisplatin: bool = Field(False)

    @field_validator("driver_type")
    @classmethod
    def driver_type_must_be_valid(cls, v: str) -> str:
        allowed = {"EGFR", "ALK", "ROS1", "NONE"}
        if v not in allowed:
            raise ValueError(
                f"driver_type must be one of {allowed}, got '{v}'. "
                "Add to allowed set if a new driver is being introduced."
            )
        return v

    model_config = {"extra": "allow"}


class PolicyOptionSchema(BaseModel):
    regimen:  str       = Field(..., description="Canonical regimen name")
    line:     str       = Field(..., description="first-line | progression")
    evidence: str       = Field(..., description="Guideline/trial citation")
    tags:     TagSchema
    requires: Dict[str, Any] = Field(
        default_factory=dict,
        description="Biomarker requirements evaluated against patient.biomarkers"
    )

    @field_validator("line")
    @classmethod
    def line_must_be_valid(cls, v: str) -> str:
        allowed = {"first-line", "progression"}
        if v not in allowed:
            raise ValueError(f"line must be 'first-line' or 'progression', got '{v}'")
        return v


class CancerPolicySchema(BaseModel):
    options_first_line:  List[PolicyOptionSchema] = Field(default_factory=list)
    options_progression: List[PolicyOptionSchema] = Field(default_factory=list)
    options_third_line:  List[PolicyOptionSchema] = Field(default_factory=list)  # PHASE 10: 3L support


class PolicyConfigSchema(BaseModel):
    """Top-level schema for the `policy` section of pathways.yaml."""
    policy: Dict[str, CancerPolicySchema]

    @model_validator(mode="after")
    def policy_must_not_be_empty(self) -> "PolicyConfigSchema":
        if not self.policy:
            raise ValueError("policy section must contain at least one cancer type.")
        return self


# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    Phase 6A: Policy layer — defines the universe of valid options.

    Instantiated once at startup. Thread-safe for read-only evaluation.
    ConstraintEngine takes our output and filters it — we never call Constraint here.
    """

    def __init__(self, config: PolicyConfigSchema) -> None:
        self._policy: Dict[str, CancerPolicySchema] = config.policy
        logger.info(
            "PolicyEngine loaded: cancer_types=%s",
            list(self._policy.keys())
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_options(self, patient: dict) -> Dict[str, Any]:
        """
        Return all guideline-valid options for this patient.

        Args:
            patient: dict with fields matching Phase 6A patient model:
                disease, stage, ecog
                biomarkers: {egfr_mutation, alk_rearrangement, ros1_fusion,
                              pd_l1, egfr_t790m}
                progression_type: None | "first-line" | "progression"
                organ_function: {renal, hepatic}
                marrow_status, prior_therapy, brain_mets,
                brain_mets_symptomatic, disease_burden

        Returns:
            {
                "options":  [ PolicyOption dicts ],
                "warnings": [ str ],         # never empty on zero results
                "cancer_type": str,
                "line_mode": "first-line" | "progression"
            }
        """
        warnings: List[str] = []

        cancer_type = (patient.get("disease") or "").lower()
        if not cancer_type:
            return self._empty_result("patient.disease (cancer type) is required.", warnings)

        catalogue = self._policy.get(cancer_type)
        if catalogue is None:
            return self._empty_result(
                f"No policy catalogue for cancer_type='{cancer_type}'. "
                f"Supported: {list(self._policy.keys())}.",
                warnings
            )

        # Extract biomarkers from patient dict
        biomarkers = patient.get("biomarkers", {})

        # Determine line mode from progression_type or explicit line number
        progression_type = patient.get("progression_type")
        line_number = patient.get("line", 1) or 1
        if line_number >= 3:
            line_mode = "third-line"
        elif line_number == 2 or progression_type == "progression":
            line_mode = "progression"
        else:
            line_mode = "first-line"

        if line_mode == "third-line":
            raw_options = catalogue.options_third_line
        elif line_mode == "progression":
            raw_options = catalogue.options_progression
        else:
            raw_options = catalogue.options_first_line
        matched: List[dict] = []

        for opt in raw_options:
            ok, skip_reason = self._biomarker_match(opt, biomarkers)
            if not ok:
                logger.debug(
                    "PolicyEngine: skipped regimen='%s' reason='%s'",
                    opt.regimen, skip_reason
                )
                continue

            # Build output dict — tags always include driver_type, IO, chemo, CNS_active
            tag_dict = {
                "driver_type": opt.tags.driver_type,
                "IO":          opt.tags.IO,
                "chemo":       opt.tags.chemo,
            }
            if opt.tags.CNS_active:
                tag_dict["CNS_active"] = True
            if opt.tags.contains_cisplatin:
                tag_dict["contains_cisplatin"] = True

            matched.append({
                "regimen":  opt.regimen,
                "line":     opt.line,
                "evidence": opt.evidence,
                "tags":     tag_dict,
            })

        if not matched:
            warnings.append(
                f"PolicyEngine: no options matched for cancer_type='{cancer_type}' "
                f"line_mode='{line_mode}' with provided biomarkers. "
                "Verify biomarker panel is complete before proceeding."
            )

        return {
            "options":     matched,
            "warnings":    warnings,
            "cancer_type": cancer_type,
            "line_mode":   line_mode,
        }

    def summary(self) -> dict:
        """Return policy summary — used by GET /phase6/policy."""
        return {
            "cancer_types": list(self._policy.keys()),
            "option_counts": {
                ct: {
                    "first_line":  len(cat.options_first_line),
                    "progression": len(cat.options_progression),
                }
                for ct, cat in self._policy.items()
            }
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _biomarker_match(
        opt: PolicyOptionSchema,
        biomarkers: dict,
    ) -> tuple[bool, Optional[str]]:
        """
        Check all `requires` constraints against patient.biomarkers.

        Supported require keys:
            egfr_mutation       : bool
            alk_rearrangement   : bool
            ros1_fusion         : bool
            egfr_t790m          : bool
            pd_l1_gte           : float  (patient pd_l1 must be >= this value)

        Returns (True, None) if all requirements met.
        Returns (False, reason) if any requirement fails or data is missing.
        """
        requires = opt.requires
        if not requires:
            return True, None

        for key, expected in requires.items():

            if key == "pd_l1_gte":
                pd_l1 = biomarkers.get("pd_l1")
                if pd_l1 is None:
                    return False, f"pd_l1 not provided; cannot evaluate pd_l1_gte={expected}"
                if float(pd_l1) < float(expected):
                    return False, f"pd_l1={pd_l1} < required {expected}"
                continue

            # Boolean biomarker keys
            patient_val = biomarkers.get(key)
            if patient_val is None:
                # Missing biomarker — conservative: exclude driver-positive regimens,
                # include driver-negative regimens
                if expected is True:
                    return False, f"biomarker '{key}' not tested; driver-positive regimen excluded"
                # expected is False → unknown status, include cautiously
                continue

            actual_bool = bool(patient_val)
            if actual_bool != bool(expected):
                return False, f"{key}={actual_bool} does not match required {expected}"

        return True, None

    @staticmethod
    def _empty_result(warning: str, warnings: List[str]) -> dict:
        warnings.append(warning)
        return {
            "options":     [],
            "warnings":    warnings,
            "cancer_type": None,
            "line_mode":   None,
        }


# ---------------------------------------------------------------------------
# Factory — called once at startup from main.py / bridge
# ---------------------------------------------------------------------------

def load_policy_engine(yaml_path: Path = PATHWAYS_YAML_PATH) -> PolicyEngine:
    """
    Load and validate the `policy` section of pathways.yaml.
    Raises on any schema error — fail-fast, never silent.
    Call at server startup, not per-request.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Pathways YAML not found at {yaml_path}. "
            "Phase 6A policy rules are required for operation."
        )

    with yaml_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if "policy" not in raw:
        raise ValueError(
            f"pathways.yaml at {yaml_path} has no 'policy' section. "
            "Phase 6A requires a top-level 'policy' key alongside 'pathways'."
        )

    config = PolicyConfigSchema.model_validate(raw)
    return PolicyEngine(config)


# Module-level singleton — imported by constraint_engine.py and med_brain.py
try:
    POLICY_ENGINE: Optional[PolicyEngine] = load_policy_engine()
except Exception as exc:
    raise RuntimeError(
        f"PolicyEngine failed to load clinical/pathways.yaml: {exc}"
    ) from exc
