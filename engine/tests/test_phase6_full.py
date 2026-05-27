"""
tests/test_phase6_full.py — Zyphraxis Phase 6 Master Validation Suite

Runs all 15 test cases across Phase 6A, 6B, and 6C (integration).

Run from project root:
    python tests/test_phase6_full.py
    # or:
    python -m pytest tests/test_phase6_full.py -v

Exit 0 = ALL PASSED.  Exit 1 = failures present.
"""
from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from clinical.policy_engine      import load_policy_engine
from clinical.constraint_engine  import ConstraintEngine
from clinical.apollo_mode        import ApolloMode
from clinical.manhattan_mode     import ManhattanMode
from engine.hybrid_engine        import HybridEngine
from engine.justification_engine import JustificationEngine
from pipeline_integration        import (
    run_phase6,
    _build_safe_options,
    _normalise_patient,
)


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

POLICY     = load_policy_engine()
CONSTRAINT = ConstraintEngine()
APOLLO     = ApolloMode()
MANHATTAN  = ManhattanMode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TR:
    def __init__(self, name: str):
        self.name     = name
        self.passed   = True
        self.failures: list[str] = []

    def ok(self, condition: bool, msg: str):
        if not condition:
            self.passed = False
            self.failures.append(f"    FAIL: {msg}")

    def report(self):
        status = "PASS ✓" if self.passed else "FAIL ✗"
        print(f"\n[{status}] {self.name}")
        for f in self.failures:
            print(f)


def _base_patient(**overrides) -> dict:
    """Minimal Phase 6A patient for policy/constraint tests."""
    p = {
        "disease": "lung",
        "stage": "IV",
        "ecog": 1,
        "biomarkers": {
            "egfr_mutation":     False,
            "alk_rearrangement": False,
            "ros1_fusion":       False,
            "pd_l1":             0,
            "egfr_t790m":        False,
        },
        "organ_function": {"renal": "normal", "hepatic": "normal"},
        "marrow_status":          "normal",
        "prior_therapy":          None,
        "progression_type":       None,
        "brain_mets":             False,
        "brain_mets_symptomatic": False,
        "disease_burden":         "moderate",
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k] = {**p[k], **v}
        else:
            p[k] = v
    return p


def _integration_patient(**overrides) -> dict:
    """Phase 6C integration patient dict (Phase 5-style schema)."""
    p = {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {},
        "pdl1":                 0,
        "driver_mutation":      None,
        "mutation":             None,
        "line":                 1,
        "ecog_status":          1,
        "creatinine_clearance": 90.0,
        "contraindications":    [],
        "tumor_escape_h":       504,
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k] = {**p[k], **v}
        else:
            p[k] = v
    return p


def _run_integration(patient: dict):
    """
    Run the full integration path and return raw intermediates for assertions.
    Uses the proper Phase 6A/6B/6C class instances, not legacy helpers.
    """
    # Normalise to Phase 6A format
    p6a = _normalise_patient(patient)

    # Phase 6A
    policy_opts       = POLICY.get_options(p6a)["options"]
    constraint_result = CONSTRAINT.filter(p6a, policy_opts)
    safe_6a           = constraint_result.get("safe_options", [])

    # LUNG_TREATMENTS eligibility (for HybridEngine + JustificationEngine)
    safe_options, rejected = _build_safe_options(p6a)

    if not safe_options:
        empty_hybrid = {"final_regimen": "NO_PATH", "line": 0, "confidence": 0.0, "_debug": {}}
        empty_just   = {"final": {}, "options": [], "safety_warnings": []}
        return run_phase6(patient), empty_hybrid, empty_just, {}, rejected

    # Phase 6B
    apollo_safe   = safe_6a if safe_6a else safe_options
    apollo_raw    = APOLLO.decide(apollo_safe, p6a)
    apollo_out    = {
        "final_regimen": apollo_raw.get("choice", ""),
        "line":          1,
        "confidence":    0.85,
        "mode":          "apollo",
    }

    manhattan_safe   = safe_6a if safe_6a else safe_options
    manhattan_ranked = MANHATTAN.evaluate(manhattan_safe, p6a)
    manhattan_out    = {}
    if manhattan_ranked:
        top = manhattan_ranked[0]
        manhattan_out = {
            "final_regimen": top.get("regimen", ""),
            "line":          1,
            "confidence":    0.82,
            "mode":          "manhattan",
        }

    # Phase 6C
    hybrid_out = HybridEngine().select(
        apollo_output    = apollo_out,
        manhattan_output = manhattan_out,
        safe_options     = safe_options,
        patient_context  = patient,
    )
    justification = JustificationEngine().generate(
        all_options      = safe_options,
        rejected_options = rejected,
        final_selection  = hybrid_out,
        hybrid_debug     = hybrid_out.get("_debug", {}),
        patient_context  = patient,
    )
    output_str = run_phase6(patient)
    return output_str, hybrid_out, justification, apollo_out, rejected


# ===========================================================================
# PHASE 6A TESTS — Policy + Constraint layer
# ===========================================================================

def test_6a_case1_egfr_pdl1_high():
    r = TR("6A-1 | EGFR+ PD-L1 75% → Osimertinib in safe; IO monotherapy excluded")
    patient = _base_patient(biomarkers={
        "egfr_mutation": True, "alk_rearrangement": False,
        "ros1_fusion": False, "pd_l1": 75, "egfr_t790m": False,
    })
    policy_opts = POLICY.get_options(patient)["options"]
    result      = CONSTRAINT.filter(patient, policy_opts)
    safe_regimens = [o["regimen"] for o in result["safe_options"]]

    r.ok(any("Osimertinib" in reg for reg in safe_regimens),
         f"Osimertinib not in safe_options: {safe_regimens}")
    r.ok(not any("Pembrolizumab monotherapy" in reg for reg in safe_regimens),
         f"IO monotherapy should be excluded for EGFR+: {safe_regimens}")
    osim = next((o for o in result["safe_options"] if "Osimertinib" in o["regimen"]), None)
    if osim:
        r.ok("driver_matched_egfr" in osim.get("priority_tags", []),
             f"Osimertinib missing driver_matched_egfr tag: {osim.get('priority_tags')}")
    r.report()
    return r.passed


def test_6a_case2_severe_renal():
    r = TR("6A-2 | Severe renal → cisplatin blocked; carboplatin safe")
    patient = _base_patient(
        organ_function={"renal": "severe", "hepatic": "normal"},
        biomarkers={"egfr_mutation": False, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 30, "egfr_t790m": False},
    )
    policy_opts = POLICY.get_options(patient)["options"]
    result = CONSTRAINT.filter(patient, policy_opts)
    safe_regimens    = [o["regimen"] for o in result["safe_options"]]
    blocked_regimens = [o["regimen"] for o in result["blocked_options"]]

    r.ok(any("Cisplatin" in reg for reg in blocked_regimens),
         f"Cisplatin not blocked: {blocked_regimens}")
    r.ok(any("Carboplatin" in reg for reg in safe_regimens),
         f"Carboplatin incorrectly blocked: {safe_regimens}")
    r.report()
    return r.passed


def test_6a_case3_marrow_suppression():
    r = TR("6A-3 | Marrow suppressed → all chemo blocked; non-chemo safe")
    patient = _base_patient(
        marrow_status="suppressed",
        biomarkers={"egfr_mutation": False, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 60, "egfr_t790m": False},
    )
    policy_opts = POLICY.get_options(patient)["options"]
    result = CONSTRAINT.filter(patient, policy_opts)
    safe = result["safe_options"]
    chemo_in_safe  = [o["regimen"] for o in safe if o.get("tags", {}).get("chemo")]
    non_chemo_safe = [o["regimen"] for o in safe if not o.get("tags", {}).get("chemo")]

    r.ok(len(chemo_in_safe) == 0,
         f"Chemo in safe_options despite suppressed marrow: {chemo_in_safe}")
    r.ok(len(non_chemo_safe) > 0,
         f"No non-chemo safe options: {[o['regimen'] for o in result['blocked_options']]}")
    r.report()
    return r.passed


def test_6a_case4_brain_mets():
    r = TR("6A-4 | Brain mets + EGFR → Osimertinib cns_coverage tag; non-CNS warned")
    patient = _base_patient(
        brain_mets=True, brain_mets_symptomatic=True,
        biomarkers={"egfr_mutation": True, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 20, "egfr_t790m": False},
    )
    policy_opts = POLICY.get_options(patient)["options"]
    result = CONSTRAINT.filter(patient, policy_opts)

    safe = result["safe_options"]
    osim = next((o for o in safe if "Osimertinib" in o["regimen"]), None)
    r.ok(osim is not None, "Osimertinib not in safe_options for EGFR+ with brain mets")
    if osim:
        r.ok("cns_coverage" in osim.get("priority_tags", []),
             f"Osimertinib missing cns_coverage tag: {osim.get('priority_tags')}")

    for opt in result["all_options"]:
        if not opt.get("tags", {}).get("CNS_active", False):
            has_warn = any("brain" in w.lower() or "cns" in w.lower()
                           for w in opt.get("warnings", []))
            r.ok(has_warn, f"{opt['regimen']} missing brain mets warning")
    r.report()
    return r.passed


def test_6a_case5_extreme_constraints():
    r = TR("6A-5 | All constraints extreme → no crash; Osimertinib survives (TKI)")
    patient = _base_patient(
        organ_function={"renal": "severe", "hepatic": "severe"},
        marrow_status="suppressed",
        brain_mets=True, brain_mets_symptomatic=True,
        disease_burden="high",
        biomarkers={"egfr_mutation": True, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 10, "egfr_t790m": False},
    )
    try:
        policy_opts = POLICY.get_options(patient)["options"]
        result = CONSTRAINT.filter(patient, policy_opts)
    except Exception as exc:
        r.ok(False, f"Engine crashed: {type(exc).__name__}: {exc}")
        r.report()
        return r.passed

    for key in ("safe_options", "blocked_options", "all_options", "warnings"):
        r.ok(key in result, f"Missing key '{key}'")
    if not result.get("safe_options"):
        r.ok(len(result.get("warnings", [])) > 0, "Empty safe_options but no warnings")

    blocked_regimens = [o["regimen"] for o in result.get("blocked_options", [])]
    r.ok(not any("Osimertinib" in reg for reg in blocked_regimens),
         "Osimertinib incorrectly blocked — TKI should survive marrow/renal/cisplatin checks")
    r.report()
    return r.passed


# ===========================================================================
# PHASE 6B TESTS — Apollo + Manhattan reasoning
# ===========================================================================

def _run_6b(patient: dict, mode="both"):
    """Run policy → constraint → Apollo/Manhattan (Phase 6A patient format)."""
    policy_opts = POLICY.get_options(patient)["options"]
    result      = CONSTRAINT.filter(patient, policy_opts)
    safe        = result["safe_options"]
    apollo      = APOLLO.decide(safe, patient)     if mode in ("apollo",    "both") else None
    manhattan   = MANHATTAN.evaluate(safe, patient) if mode in ("manhattan", "both") else None
    return safe, apollo, manhattan


def test_6b_case1_simple_egfr():
    r = TR("6B-1 | EGFR+ → Apollo == Manhattan rank-1 == Osimertinib")
    patient = _base_patient(biomarkers={
        "egfr_mutation": True, "alk_rearrangement": False,
        "ros1_fusion": False, "pd_l1": 10, "egfr_t790m": False,
    })
    safe, apollo, manhattan = _run_6b(patient)

    r.ok(apollo is not None, "Apollo returned None")
    if apollo:
        r.ok("Osimertinib" in apollo["choice"],
             f"Apollo should choose Osimertinib: {apollo['choice']}")
        r.ok(apollo["priority_used"] == "driver_mutation",
             f"Apollo priority should be driver_mutation: {apollo['priority_used']}")
    if manhattan and apollo:
        r.ok(manhattan[0]["regimen"] == apollo["choice"],
             f"Manhattan rank-1 '{manhattan[0]['regimen']}' != Apollo '{apollo['choice']}'")
    r.report()
    return r.passed


def test_6b_case2_complex_no_driver():
    r = TR("6B-2 | No driver, PD-L1 35% → Manhattan multi-option; Apollo picks one")
    patient = _base_patient(biomarkers={
        "egfr_mutation": False, "alk_rearrangement": False,
        "ros1_fusion": False, "pd_l1": 35, "egfr_t790m": False,
    })
    safe, apollo, manhattan = _run_6b(patient)

    r.ok(manhattan is not None and len(manhattan) > 1,
         f"Manhattan should return >1 option: {len(manhattan or [])}")
    r.ok(apollo is not None and isinstance(apollo["choice"], str),
         "Apollo must return a single string choice")
    if apollo and manhattan:
        manhattan_regimens = [o["regimen"] for o in manhattan]
        r.ok(apollo["choice"] in manhattan_regimens,
             f"Apollo '{apollo['choice']}' not in Manhattan options: {manhattan_regimens}")
    r.report()
    return r.passed


def test_6b_case3_t790m_progression():
    r = TR("6B-3 | T790M+ progression → both engines pick Osimertinib T790M+")
    patient = _base_patient(
        progression_type="progression",
        biomarkers={"egfr_mutation": True, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 15, "egfr_t790m": True},
    )
    safe, apollo, manhattan = _run_6b(patient)

    if apollo:
        r.ok("Osimertinib" in apollo["choice"] and "T790M" in apollo["choice"],
             f"Apollo should pick Osimertinib T790M+: {apollo['choice']}")
        r.ok(apollo["priority_used"] == "resistance_match",
             f"Apollo priority should be resistance_match: {apollo['priority_used']}")
    if manhattan and len(manhattan) > 0:
        r.ok("Osimertinib" in manhattan[0]["regimen"] and "T790M" in manhattan[0]["regimen"],
             f"Manhattan rank-1 should be Osimertinib T790M+: {manhattan[0]['regimen']}")
    r.report()
    return r.passed


def test_6b_case4_brain_mets():
    r = TR("6B-4 | EGFR+ brain mets → both engines prioritise CNS-active option")
    patient = _base_patient(
        brain_mets=True, brain_mets_symptomatic=True,
        biomarkers={"egfr_mutation": True, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 5, "egfr_t790m": False},
    )
    safe, apollo, manhattan = _run_6b(patient)

    if apollo:
        r.ok(apollo["priority_used"] in ("cns_disease", "driver_mutation"),
             f"Apollo priority should be cns_disease or driver_mutation: {apollo['priority_used']}")
        r.ok("Osimertinib" in apollo["choice"],
             f"Apollo should choose CNS-active Osimertinib: {apollo['choice']}")
    r.report()
    return r.passed


def test_6b_case5_high_burden():
    r = TR("6B-5 | High burden PD-L1 60% → chemo-IO preferred over IO monotherapy")
    patient = _base_patient(
        disease_burden="high",
        biomarkers={"egfr_mutation": False, "alk_rearrangement": False,
                    "ros1_fusion": False, "pd_l1": 60, "egfr_t790m": False},
    )
    safe, apollo, manhattan = _run_6b(patient)

    if apollo:
        r.ok("monotherapy" not in apollo["choice"].lower(),
             f"Apollo at high burden should prefer combo over monotherapy: {apollo['choice']}")
    if manhattan and len(manhattan) > 0:
        r.ok("monotherapy" not in manhattan[0]["regimen"].lower(),
             f"Manhattan rank-1 at high burden should be combo: {manhattan[0]['regimen']}")
    r.report()
    return r.passed


# ===========================================================================
# PHASE 6C INTEGRATION TESTS
# ===========================================================================

def test_6c_case1_egfr_io_rejected():
    r = TR("6C-1 | EGFR+ PD-L1 70% → Osimertinib; IO rejected with EGFR justification")
    patient = _integration_patient(
        biomarkers={"EGFR": "positive", "PD-L1": "positive"},
        pdl1=70.0,
        driver_mutation="EGFR",
        mutation="EGFR",
    )
    output_str, hybrid_out, justification, apollo_out, rejected = _run_integration(patient)
    print(output_str)

    r.ok("osimertinib" in hybrid_out["final_regimen"].lower(),
         f"Final regimen should be Osimertinib: {hybrid_out['final_regimen']}")
    r.ok("osimertinib" in apollo_out.get("final_regimen", "").lower(),
         f"Apollo should select Osimertinib: {apollo_out.get('final_regimen')}")
    io_rej = next((o for o in justification["options"]
                   if "pembrolizumab" in o["name"].lower()), None)
    r.ok(io_rej is not None and bool(io_rej.get("why_rejected")),
         "Pembrolizumab should be rejected with justification")
    if io_rej:
        rej_text = (io_rej.get("why_rejected") or "").lower()
        r.ok("egfr" in rej_text or "contraindicated" in rej_text,
             f"IO rejection should reference EGFR: {io_rej.get('why_rejected')}")
    r.ok(hybrid_out["confidence"] > 0.5, f"Confidence > 0.5: {hybrid_out['confidence']}")
    r.report()
    return r.passed


def test_6c_case2_pdl1_high_no_driver():
    r = TR("6C-2 | PD-L1 75%, no driver → Pembrolizumab selected")
    patient = _integration_patient(
        biomarkers={"PD-L1": "positive", "EGFR": "negative", "ALK": "negative"},
        pdl1=75.0,
        driver_mutation=None,
        mutation=None,
    )
    _, hybrid_out, justification, _, _ = _run_integration(patient)

    r.ok("pembrolizumab" in hybrid_out["final_regimen"].lower(),
         f"Final regimen should be Pembrolizumab: {hybrid_out['final_regimen']}")
    r.ok(bool(justification["final"]["why_selected"]),
         "Final selection has no justification text")
    r.ok(hybrid_out["confidence"] > 0.5, f"Confidence > 0.5: {hybrid_out['confidence']}")
    r.report()
    return r.passed


def test_6c_case3_t790m_second_line():
    r = TR("6C-3 | T790M+ progression line 2 → Osimertinib 2L; T790M in justification")
    patient = _integration_patient(
        biomarkers={"EGFR": "positive", "T790M": "positive"},
        driver_mutation="EGFR",
        mutation="EGFR",
        resistance_mutation="T790M",
        line=2,
        creatinine_clearance=75.0,
    )
    output_str, hybrid_out, justification, apollo_out, _ = _run_integration(patient)

    r.ok("osimertinib" in hybrid_out["final_regimen"].lower(),
         f"Final regimen should be Osimertinib: {hybrid_out['final_regimen']}")
    r.ok(hybrid_out["line"] == 2,
         f"Line of therapy should be 2: {hybrid_out['line']}")
    why = justification["final"]["why_selected"].lower()
    r.ok("t790m" in why or "resistance" in why,
         f"Why-selected should reference T790M: {justification['final']['why_selected']}")
    t790m_warning = any("T790M" in w for w in justification["safety_warnings"])
    r.ok(t790m_warning, "T790M safety warning should be present")
    r.ok("osimertinib" in apollo_out.get("final_regimen", "").lower(),
         f"Apollo should pick Osimertinib: {apollo_out.get('final_regimen')}")
    r.report()
    return r.passed


def test_6c_case4_alk_brain_mets():
    r = TR("6C-4 | ALK+ brain mets → Alectinib; CNS in justification and warnings")
    patient = _integration_patient(
        biomarkers={"ALK": "positive", "EGFR": "negative", "PD-L1": "negative"},
        driver_mutation="ALK",
        mutation="ALK",
        brain_mets=True,
        cns_disease=True,
    )
    _, hybrid_out, justification, apollo_out, _ = _run_integration(patient)

    r.ok("alectinib" in hybrid_out["final_regimen"].lower(),
         f"Final regimen should be Alectinib: {hybrid_out['final_regimen']}")
    why = justification["final"]["why_selected"].lower()
    r.ok("cns" in why or "brain" in why or "intracranial" in why,
         f"Why-selected should reference CNS: {justification['final']['why_selected']}")
    cns_warning = any("CNS" in w or "brain" in w.lower()
                      for w in justification["safety_warnings"])
    r.ok(cns_warning, "CNS/brain mets safety warning should be present")
    r.ok("alectinib" in apollo_out.get("final_regimen", "").lower(),
         f"Apollo should select Alectinib: {apollo_out.get('final_regimen')}")
    r.ok(hybrid_out["confidence"] > 0.5, f"Confidence > 0.5: {hybrid_out['confidence']}")
    r.report()
    return r.passed


def test_6c_case5_severe_renal_cisplatin_excluded():
    r = TR("6C-5 | CrCl 22 (severe renal) → cisplatin excluded; renal warning; safe regimen")
    patient = _integration_patient(
        biomarkers={"PD-L1": "positive", "EGFR": "negative", "ALK": "negative"},
        pdl1=60.0,
        creatinine_clearance=22.0,
    )
    output_str, hybrid_out, justification, _, rejected = _run_integration(patient)

    r.ok("cisplatin" not in hybrid_out["final_regimen"].lower(),
         f"Final regimen must not contain cisplatin: {hybrid_out['final_regimen']}")
    renal_warning = any(
        "RENAL" in w or "creatinine" in w.lower() or "cisplatin" in w.lower()
        for w in justification["safety_warnings"]
    )
    r.ok(renal_warning, "Renal / cisplatin safety warning should be present")
    cisplatin_excluded = any(
        "cisplatin" in r_item.get("treatment_name", "").lower() for r_item in rejected
    ) or not any(
        "cisplatin" in o["name"].lower()
        for o in justification.get("options", []) if not o.get("why_rejected")
    )
    r.ok(cisplatin_excluded, "Cisplatin should be excluded from eligible options")
    safe_name = hybrid_out["final_regimen"].lower()
    r.ok(
        any(x in safe_name for x in ("carboplatin", "pembrolizumab", "osimertinib",
                                      "alectinib", "atezolizumab", "entrectinib")),
        f"Selected regimen should be renal-safe: {hybrid_out['final_regimen']}"
    )
    r.report()
    return r.passed


# ===========================================================================
# Runner
# ===========================================================================

def run_all():
    print("=" * 70)
    print("ZYPHRAXIS PHASE 6 — MASTER VALIDATION SUITE")
    print("=" * 70)

    test_groups = [
        ("─── Phase 6A: Policy + Constraint ───", [
            test_6a_case1_egfr_pdl1_high,
            test_6a_case2_severe_renal,
            test_6a_case3_marrow_suppression,
            test_6a_case4_brain_mets,
            test_6a_case5_extreme_constraints,
        ]),
        ("─── Phase 6B: Apollo + Manhattan ───", [
            test_6b_case1_simple_egfr,
            test_6b_case2_complex_no_driver,
            test_6b_case3_t790m_progression,
            test_6b_case4_brain_mets,
            test_6b_case5_high_burden,
        ]),
        ("─── Phase 6C: Integration ───", [
            test_6c_case1_egfr_io_rejected,
            test_6c_case2_pdl1_high_no_driver,
            test_6c_case3_t790m_second_line,
            test_6c_case4_alk_brain_mets,
            test_6c_case5_severe_renal_cisplatin_excluded,
        ]),
    ]

    total  = 0
    passed = 0
    all_failures: list[str] = []

    for header, tests in test_groups:
        print(f"\n{header}")
        for fn in tests:
            total += 1
            try:
                ok = fn()
                if ok:
                    passed += 1
            except Exception as exc:
                import traceback
                print(f"\n  ✗  EXCEPTION in {fn.__name__}: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                all_failures.append(f"{fn.__name__}: {exc}")

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed}/{total} tests passed")
    if passed == total:
        print("\n✅  Phase 6 Upgrade Validated — ALL TESTS PASSED")
    else:
        print(f"\n❌  {total - passed} test(s) FAILED")
        for f in all_failures:
            print(f"   • {f}")
    print("=" * 70)
    return passed == total


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
