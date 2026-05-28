"""
main.py — Zyphraxis Phase 6 Entry Point

Usage modes:

  1. API server (recommended for integration):
         uvicorn main:app --reload --port 8000

  2. CLI single-patient run:
         python main.py egfr_firstline
         python main.py t790m_progression
         python main.py alk_brain_mets
         python main.py pdl1_high_no_driver
         python main.py renal_impaired

  3. API server direct:
         python main.py --serve

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from pipeline_integration import run_phase6, _POLICY, _CONSTRAINT

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "6.0.0"

CDSS_DISCLAIMER = (
    "This output was produced by a Clinical Decision Support System (CDSS). "
    "It must be reviewed by a licensed oncologist before any clinical action. "
    "The physician's decision — not this output — is the clinical record. "
    "Research use only. Not a licensed medical device."
)


# ── Example patients — covering all major Phase 6 scenarios ──────────────────

EXAMPLE_PATIENTS = {

    "egfr_firstline": {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"EGFR": "positive"},
        "driver_mutation":      "EGFR",
        "mutation":             "EGFR",
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 85.0,
        "contraindications":    [],
        "tumor_escape_h":       504,
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
    # Phase 5-style fields (backward-compatible)
    cancer_type:          Optional[str]            = Field(None, description="lung | breast | colorectal")
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
    disease_burden:       Optional[str]            = Field(None)

    # Phase 6A-style fields (native format)
    disease:              Optional[str]            = Field(None)
    organ_function:       Optional[Dict[str, str]] = Field(None)
    marrow_status:        Optional[str]            = Field(None)
    progression_type:     Optional[str]            = Field(None)


class Phase6Response(BaseModel):
    output:                    str
    version:                   str = VERSION
    physician_review_required: bool = True
    cdss_disclaimer:           str  = CDSS_DISCLAIMER
    error:                     Optional[str] = None


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Singletons already loaded at import time in pipeline_integration.py
    # This is just for logging / future startup hooks
    import logging
    logging.basicConfig(level="INFO")
    logging.getLogger("uvicorn").info(f"Zyphraxis Phase 6 v{VERSION} ready.")
    yield


app = FastAPI(
    title       = "Zyphraxis Phase 6 — Clinical Decision Pipeline",
    version     = VERSION,
    description = (
        "AI-driven NSCLC treatment sequencing. Phase 6A (policy/constraint) → "
        "6B (Apollo/Manhattan) → 6C (hybrid arbitration + justification). "
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
    return {"status": "ok", "version": VERSION, "phase": "6"}


@app.get("/phase6/policy", tags=["phase6"])
def get_policy_summary() -> dict:
    """Return the loaded Phase 6A policy catalogue summary."""
    return {
        "policy_summary": _POLICY.summary(),
        "note": (
            "Policy rules are defined in clinical/pathways.yaml. "
            "Editing requires a YAML file change and server restart."
        ),
    }


@app.post("/phase6/decide", response_model=Phase6Response, tags=["phase6"])
def decide(request: Phase6Request) -> Phase6Response:
    """
    Run the full Phase 6 pipeline for a patient and return a structured
    treatment recommendation with justification.
    """
    patient = request.model_dump(exclude_none=False)
    try:
        output = run_phase6(patient)
        return Phase6Response(output=output)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/version", tags=["system"])
def version() -> dict:
    return {"version": VERSION, "phase": "6"}


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
        print(f"Running Phase 6 Pipeline — Patient: {case_name}")
        print(f"{'='*70}\n")
        result = run_phase6(patient)
        print(result)
        print(f"\n{'='*70}")
        print(CDSS_DISCLAIMER)
        print(f"{'='*70}\n")
import httpx

class ProxyRequest(BaseModel):
    payload: Dict[str, Any]
    api_key: str

@app.post("/proxy/anthropic", tags=["system"])
async def proxy_anthropic(request: ProxyRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": request.api_key,
                "anthropic-version": "2023-06-01"
            },
            json=request.payload,
            timeout=30.0
        )
        return resp.json()
