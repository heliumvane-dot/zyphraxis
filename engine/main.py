"""
main.py — Zyphraxis Phase 11 Entry Point

Updates from Phase 10:
  1. egfr_subtype field added to Phase6Request (exon19del | L858R | exon20ins | other)
  2. EGFR Exon 20 insertion routing — amivantamab/mobocertinib, NOT osimertinib
  3. FLAURA2 escalation flag for high disease burden EGFR+ cases
  4. EGFR subtype confidence adjustment (L858R slightly lower than exon19del)
  5. prior_therapies field exposed in API
  6. PatientJourney field exposed in API
  7. /proxy/anthropic endpoint for browser-based UI
  8. /run alias endpoint for frontend compatibility

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from pipeline_integration import run_phase6, _POLICY, _CONSTRAINT

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "11.0.0"

CDSS_DISCLAIMER = (
    "This output was produced by a Clinical Decision Support System (CDSS). "
    "It must be reviewed by a licensed oncologist before any clinical action. "
    "The physician's decision — not this output — is the clinical record. "
    "Research use only. Not a licensed medical device."
)

# ── Example patients ──────────────────────────────────────────────────────────
EXAMPLE_PATIENTS = {

    "egfr_exon19_firstline": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"EGFR": "positive"},
        "driver_mutation":      "EGFR",
        "mutation":             "EGFR",
        "egfr_subtype":         "exon19del",
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 85.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    },

    "egfr_l858r_firstline": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"EGFR": "positive"},
        "driver_mutation":      "EGFR",
        "mutation":             "EGFR",
        "egfr_subtype":         "L858R",
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 85.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    },

    "egfr_exon20ins": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"EGFR": "exon_20_insertion"},
        "driver_mutation":      "EGFR",
        "mutation":             "EGFR",
        "egfr_subtype":         "exon20ins",
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 80.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    },

    "egfr_high_burden_flaura2": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"EGFR": "positive"},
        "driver_mutation":      "EGFR",
        "egfr_subtype":         "exon19del",
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 75.0,
        "disease_burden":       "high",
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    },

    "t790m_progression": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"EGFR": "positive", "T790M": "positive"},
        "driver_mutation":      "EGFR",
        "mutation":             "EGFR",
        "resistance_mutation":  "T790M",
        "prior_therapies":      ["Erlotinib 1L"],
        "line":                 2,
        "ecog_status":          1,
        "creatinine_clearance": 75.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
    },

    "alk_brain_mets": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"ALK": "positive"},
        "driver_mutation":      "ALK",
        "mutation":             "ALK",
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 88.0,
        "contraindications":    [],
        "brain_mets":           True,
        "cns_disease":          True,
        "resistance_mutation":  None,
    },

    "pdl1_high_no_driver": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"PD-L1": 0.75},
        "driver_mutation":      None,
        "mutation":             None,
        "pdl1":                 0.75,
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 80.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
        "disease_burden":       "moderate",
    },

    "renal_impaired": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {},
        "driver_mutation":      None,
        "mutation":             None,
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 22.0,
        "contraindications":    ["severe_renal"],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    },
}


# ── FastAPI request/response schemas ──────────────────────────────────────────

class Phase6Request(BaseModel):
    # Core fields
    cancer_type:          Optional[str]            = Field(None, description="lung | breast | colorectal | prostate")
    stage:                Optional[str]            = Field("IV")
    biomarkers:           Dict[str, Any]           = Field(default_factory=dict)
    driver_mutation:      Optional[str]            = Field(None)
    mutation:             Optional[str]            = Field(None)
    line:                 int                      = Field(1, ge=1)
    ecog_status:          Optional[int]            = Field(None, ge=0, le=4)
    creatinine_clearance: Optional[float]          = Field(None, gt=0)
    contraindications:    List[str]                = Field(default_factory=list)
    brain_mets:           bool                     = Field(False)
    cns_disease:          bool                     = Field(False)
    resistance_mutation:  Optional[str]            = Field(None)
    pdl1:                 Optional[float]          = Field(None)
    tumor_escape_h:       Optional[float]          = Field(None)
    disease_burden:       Optional[str]            = Field(None, description="low | moderate | high")

    # Phase 11: EGFR subtype branching
    egfr_subtype:         Optional[str]            = Field(None, description="exon19del | L858R | exon20ins | other")

    # Phase 11: Prior therapy tracking
    prior_therapies:      Optional[List[str]]      = Field(None, description="List of prior regimen names e.g. ['Erlotinib 1L']")

    # Phase 11: PatientJourney
    journey_id:           Optional[str]            = Field(None, description="Patient journey ID for longitudinal tracking")

    # Phase 6A native fields
    disease:              Optional[str]            = Field(None)
    organ_function:       Optional[Dict[str, str]] = Field(None)
    marrow_status:        Optional[str]            = Field(None)
    progression_type:     Optional[str]            = Field(None)

    


class Phase6Response(BaseModel):
    output:                    str
    version:                   str = VERSION
    physician_review_required: bool = True
    cdss_disclaimer:           str  = CDSS_DISCLAIMER
    ok:                        bool = True
    error:                     Optional[str] = None
    egfr_subtype_flag:         Optional[str] = None


# ── EGFR subtype enrichment ───────────────────────────────────────────────────

def _enrich_egfr_subtype(patient: dict) -> tuple[dict, Optional[str]]:
    """
    Enrich patient dict with EGFR subtype information.
    Returns (enriched_patient, warning_string | None).

    Phase 11 logic:
    - exon20ins → set biomarkers EGFR to exon_20_insertion (routes to Amivantamab)
    - exon19del → standard Osimertinib, confidence 0.92
    - L858R     → Osimertinib, slightly lower confidence 0.87
    - other     → flag uncertainty
    - None      → flag that subtype is unknown (may affect routing)
    """
    subtype = patient.get("egfr_subtype")
    egfr_positive = str(patient.get("biomarkers", {}).get("EGFR", "")).lower() in (
        "positive", "mutated", "true", "yes", "1"
    ) or str(patient.get("driver_mutation", "")).upper() == "EGFR"

    warning = None

    if not egfr_positive:
        return patient, None

    p = dict(patient)
    bm = dict(p.get("biomarkers", {}))

    if subtype == "exon20ins":
        # Route to Amivantamab — set EGFR biomarker to exon_20_insertion
        bm["EGFR"] = "exon_20_insertion"
        p["biomarkers"] = bm
        p["egfr_subtype_routing"] = "amivantamab"
        warning = (
            "EGFR Exon 20 insertion detected. Osimertinib is NOT standard — "
            "routed to Amivantamab (CHRYSALIS trial). This is a different "
            "treatment paradigm from Exon 19 del / L858R."
        )

    elif subtype == "exon19del":
        p["egfr_subtype_routing"] = "osimertinib_standard"
        p["egfr_confidence_boost"] = 0.05  # Exon 19 del has stronger FLAURA data

    elif subtype == "L858R":
        p["egfr_subtype_routing"] = "osimertinib_l858r"
        p["egfr_confidence_boost"] = 0.0   # Slightly lower benefit vs exon19del

    elif subtype == "other":
        warning = (
            "EGFR mutation subtype is unusual or rare. Standard FLAURA data "
            "may not directly apply. Osimertinib recommended with reduced confidence — "
            "consider molecular tumour board review."
        )
        p["egfr_confidence_boost"] = -0.10

    elif subtype is None and egfr_positive:
        warning = (
            "EGFR subtype not specified. Defaulting to standard Osimertinib recommendation. "
            "Note: Exon 20 insertion requires completely different therapy (Amivantamab). "
            "Confirm mutation subtype before prescribing."
        )

    # FLAURA2 escalation flag for high disease burden
    if egfr_positive and subtype in ("exon19del", "L858R") and patient.get("line", 1) == 1:
        burden = patient.get("disease_burden", "moderate")
        if burden == "high":
            p["flaura2_candidate"] = True

    return p, warning


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    logging.basicConfig(level="INFO")
    logging.getLogger("uvicorn").info(f"Zyphraxis Phase 11 v{VERSION} ready.")
    yield


app = FastAPI(
    title       = "Zyphraxis Phase 11 — Clinical Decision Pipeline",
    version     = VERSION,
    description = (
        "AI-driven oncology treatment sequencing. "
        "Phase 11 adds EGFR subtype branching, FLAURA2 escalation, "
        "prior therapy tracking, and PatientJourney integration. "
        "Research use only."
    ),
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": VERSION, "phase": "11"}


@app.get("/version", tags=["system"])
def version_info() -> dict:
    return {"version": VERSION, "phase": "11"}


@app.get("/phase6/policy", tags=["phase6"])
def get_policy_summary() -> dict:
    return {
        "policy_summary": _POLICY.summary(),
        "note": (
            "Policy rules defined in clinical/pathways.yaml. "
            "Editing requires YAML file change and server restart."
        ),
    }


@app.post("/phase6/decide", response_model=Phase6Response, tags=["phase6"])
def decide(request: Phase6Request) -> Phase6Response:
    """
    Run the full Phase 11 pipeline for a patient.
    Now supports egfr_subtype, prior_therapies, and journey_id.
    """
    patient = request.model_dump(exclude_none=False)

    # Phase 11: EGFR subtype enrichment
    patient, egfr_warning = _enrich_egfr_subtype(patient)

    # Phase 11: prior_therapies passthrough
    if request.prior_therapies:
        patient["prior_therapies"] = request.prior_therapies

    # Phase 11: FLAURA2 note injection into output
    flaura2_note = ""
    if patient.get("flaura2_candidate"):
        flaura2_note = (
            "\n\n## FLAURA2 ESCALATION NOTE\n"
            "  High disease burden detected with EGFR+ 1L patient.\n"
            "  Consider: Osimertinib + Carboplatin + Pemetrexed (FLAURA2)\n"
            "  FLAURA2 trial: mPFS 25.5 mo vs 16.7 mo (HR 0.62) for combo vs monotherapy.\n"
            "  Indicated for: high tumour burden, rapid progression risk, visceral crisis.\n"
            "  Tradeoff: higher haematological toxicity — patient fitness must be assessed.\n"
        )

    try:
        output = run_phase6(
            patient,
            journey_id      = request.journey_id,
            storage_backend = None,
        )

        if flaura2_note:
            output = output + flaura2_note

        return Phase6Response(
            output             = output,
            egfr_subtype_flag  = egfr_warning,
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/run", response_model=Phase6Response, tags=["phase6"])
def run_alias(request: Phase6Request) -> Phase6Response:
    """
    Alias for /phase6/decide — for frontend compatibility.
    """
    return decide(request)


# ── Anthropic proxy ───────────────────────────────────────────────────────────

@app.post("/proxy/anthropic", tags=["system"])
async def proxy_anthropic(request: Request):
    """
    Proxy for Anthropic API calls from browser-based UI.
    Bypasses browser CORS restrictions by routing through this server.
    The API key is passed in x-api-key header — never stored server-side.
    """
    try:
        import anthropic
        body    = await request.json()
        api_key = request.headers.get("x-api-key", "")

        if not api_key or not api_key.startswith("sk-ant-"):
            return JSONResponse(
                status_code = 401,
                content     = {"error": {"type": "authentication_error", "message": "Invalid or missing API key"}}
            )

        client     = anthropic.Anthropic(api_key=api_key)
        model      = body.get("model", "claude-sonnet-4-5")
        max_tokens = body.get("max_tokens", 1000)
        messages   = body.get("messages", [])
        system     = body.get("system", None)

        kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)
        return response.model_dump()

    except Exception as exc:
        return JSONResponse(
            status_code = 500,
            content     = {"error": {"type": "server_error", "message": str(exc)}}
        )


# ── CLI runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "--serve":
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        case_name = args[0]
        patient   = EXAMPLE_PATIENTS.get(case_name)

        if patient is None:
            print(f"Unknown case '{case_name}'. Available: {list(EXAMPLE_PATIENTS)}")
            sys.exit(1)

        print(f"\n{'='*70}")
        print(f"Running Phase 11 Pipeline — Patient: {case_name}")
        print(f"{'='*70}\n")

        enriched, warning = _enrich_egfr_subtype(patient)
        if warning:
            print(f"⚠  EGFR NOTE: {warning}\n")

        result = run_phase6(enriched)
        print(result)
        print(f"\n{'='*70}")
        print(CDSS_DISCLAIMER)
        print(f"{'='*70}\n")
