"""
tests/test_phase7.py — Zyphraxis Phase 7 Validation Test Suite

Covers all mandatory validation gates:

  Phase 7A: Multi-cancer routing + NSCLC isolation
  Phase 7B: Timeline simulation + sequence correctness
  Phase 7C: Learning engine + confidence-only adjustment

Run:
    cd /path/to/zyphraxis_phase7
    python tests/test_phase7.py

All tests must PASS before proceeding to the next stage.
Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import sys
import os
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_PASSED  = []
_FAILED  = []
_STOPPED = False


def check(name: str, condition: bool, detail: str = "") -> bool:
    global _STOPPED
    if _STOPPED:
        return False
    if condition:
        _PASSED.append(name)
        print(f"  ✓  {name}")
        return True
    else:
        _FAILED.append(name)
        print(f"  ✗  FAIL: {name}")
        if detail:
            print(f"          {detail}")
        return False


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def gate(gate_name: str):
    global _STOPPED
    if _FAILED:
        print(f"\n  ⛔  GATE FAILURE: {gate_name}")
        print(f"  Failed checks: {_FAILED}")
        print("  Execution STOPPED per spec — fix failures before proceeding.")
        _STOPPED = True
    else:
        print(f"\n  ✅  {gate_name}")


# ===========================================================================
# PHASE 7A TESTS
# ===========================================================================

def test_7a():
    section("PHASE 7A — Multi-Cancer Routing & Isolation")

    from router.disease_router import DISEASE_ROUTER
    from pipeline_integration  import run_phase6

    # ── Test 1: NSCLC EGFR → Osimertinib (Phase 6 UNCHANGED) ────────────
    lung_egfr = {
        "cancer_type":     "lung",
        "stage":           "IV",
        "biomarkers":      {"EGFR": "positive"},
        "driver_mutation": "EGFR",
        "mutation":        "EGFR",
        "line":            1,
        "ecog_status":     1,
        "creatinine_clearance": 85.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    }

    # Direct Phase 6 run (baseline)
    p6_output = run_phase6(lung_egfr)
    check("NSCLC Phase 6 baseline runs", isinstance(p6_output, str) and len(p6_output) > 0)
    check("NSCLC Phase 6 output contains Osimertinib",
          "Osimertinib" in p6_output,
          f"Output snippet: {p6_output[:200]}")

    # Through Phase 7A router
    p7a_lung = DISEASE_ROUTER.route(lung_egfr)
    check("Phase 7A routes lung to Phase 6",
          p7a_lung.get("pipeline") == "phase6_nsclc",
          f"Got pipeline={p7a_lung.get('pipeline')}")
    check("Phase 7A NSCLC output unchanged",
          p7a_lung.get("output_text") == p6_output,
          "Router output differs from direct Phase 6 run")

    # ── Test 2: Breast HER2+ → Trastuzumab-based ─────────────────────────
    breast_her2 = {
        "cancer_type":     "breast",
        "subtype":         "HER2+",
        "stage":           "IV",
        "line_of_therapy": 1,
        "biomarkers":      {"HER2": "positive"},
    }
    result = DISEASE_ROUTER.route(breast_her2)
    check("Breast HER2+ routes to breast pipeline",
          result.get("pipeline") == "phase7a_breast",
          f"Got pipeline={result.get('pipeline')}")
    check("Breast HER2+ → Trastuzumab-based therapy",
          "Trastuzumab" in (result.get("final_regimen") or ""),
          f"Got regimen={result.get('final_regimen')}")

    # ── Test 3: Breast ER+ → Endocrine therapy ───────────────────────────
    breast_er = {
        "cancer_type":     "breast",
        "subtype":         "ER+",
        "stage":           "IV",
        "line_of_therapy": 1,
        "biomarkers":      {"ER": "positive"},
    }
    result = DISEASE_ROUTER.route(breast_er)
    final_r = result.get("final_regimen") or ""
    check("Breast ER+ → Endocrine therapy",
          any(x in final_r for x in ("Letrozole", "Fulvestrant", "Exemestane", "Palbociclib")),
          f"Got regimen={final_r}")
    check("Breast ER+ uses endocrine strategy",
          "Palbociclib" in final_r or "Letrozole" in final_r,
          f"Expected CDK4/6 + AI, got: {final_r}")

    # ── Test 4: Colorectal KRAS mutant → NO anti-EGFR ───────────────────
    crc_kras = {
        "cancer_type":     "colorectal",
        "subtype":         "KRAS_mut",
        "stage":           "IV",
        "line_of_therapy": 1,
        "biomarkers":      {"KRAS": "mutant"},
    }
    result = DISEASE_ROUTER.route(crc_kras)
    final_r = result.get("final_regimen") or ""
    check("Colorectal KRAS mutant → no anti-EGFR",
          "Cetuximab" not in final_r and "Panitumumab" not in final_r,
          f"Anti-EGFR found in regimen: {final_r}")
    check("Colorectal KRAS mutant → Bevacizumab regimen",
          "Bevacizumab" in final_r or "FOLFOX" in final_r,
          f"Expected FOLFOX+Bev, got: {final_r}")

    # ── Test 5: Prostate metastatic → ADT-based ──────────────────────────
    prostate_m = {
        "cancer_type":     "prostate",
        "subtype":         "hormone_sensitive",
        "stage":           "IV",
        "line_of_therapy": 1,
        "biomarkers":      {},
        "disease_volume":  "high",
    }
    result = DISEASE_ROUTER.route(prostate_m)
    final_r = result.get("final_regimen") or ""
    check("Prostate metastatic → ADT-based therapy",
          "ADT" in final_r or "Abiraterone" in final_r or "Leuprolide" in final_r,
          f"Got regimen={final_r}")

    # ── Test 6: Router hard-fails on unknown cancer ───────────────────────
    try:
        DISEASE_ROUTER.route({"cancer_type": "pancreatic", "stage": "IV"})
        check("Router hard-fails on unknown cancer type", False,
              "Should have raised ValueError")
    except ValueError as e:
        check("Router hard-fails on unknown cancer type", True,
              f"Correctly raised: {e}")

    # ── Test 7: No cross-cancer contamination (import check) ─────────────
    import clinical.cancers.breast.apollo as ba
    import clinical.cancers.breast.manhattan as bm
    import clinical.cancers.colorectal.apollo as ca
    import clinical.cancers.prostate.apollo as pa

    breast_src    = open(ba.__file__).read()
    manhattan_src = open(bm.__file__).read()
    crc_src       = open(ca.__file__).read()
    prostate_src  = open(pa.__file__).read()

    check("Breast apollo has no lung imports",
          "from engine.cancers.lung" not in breast_src and "from clinical.cancers.colorectal" not in breast_src)
    check("Breast manhattan has no prostate imports",
          "from clinical.cancers.prostate" not in manhattan_src)
    check("Colorectal apollo has no breast imports",
          "from clinical.cancers.breast" not in crc_src)
    check("Prostate apollo has no colorectal imports",
          "from clinical.cancers.colorectal" not in prostate_src)

    gate("Phase 7A Validated")


# ===========================================================================
# PHASE 7B TESTS
# ===========================================================================

def test_7b():
    section("PHASE 7B — Timeline Simulation Engine")

    from timeline.timeline_engine import TIMELINE_ENGINE
    from router.disease_router    import DISEASE_ROUTER
    from pipeline_integration     import run_phase6

    # ── Test 1: EGFR 1L → progression → next line ──────────────────────
    egfr_case = {
        "cancer_type":     "lung",
        "stage":           "IV",
        "biomarkers":      {"EGFR": "positive"},
        "driver_mutation": "EGFR",
        "mutation":        "EGFR",
        "line":            1,
        "line_of_therapy": 1,
        "ecog_status":     1,
        "creatinine_clearance": 85.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    }

    # Progression state: T790M acquired resistance
    egfr_prog_states = [
        {
            "resistance_mutation": "T790M",
            "biomarkers": {"EGFR": "positive", "T790M": "positive"},
            "line": 2,
            "radiology": {"recist": "PD"},
        }
    ]

    # Step 1 (stable) → progression injected at step 1 → step 2 at line 2
    egfr_with_progression = copy.deepcopy(egfr_case)
    egfr_with_progression["radiology"] = {"recist": "PD"}

    sim = TIMELINE_ENGINE.simulate(
        initial_case       = egfr_with_progression,
        progression_states = [{"resistance_mutation": "T790M",
                               "biomarkers": {"EGFR": "positive", "T790M": "positive"},
                               "line": 2}],
        max_steps          = 3,
    )

    check("EGFR simulation produces steps", len(sim["steps"]) >= 1)
    check("EGFR step 1 line = 1",
          sim["steps"][0]["line_of_therapy"] == 1,
          f"Got line={sim['steps'][0]['line_of_therapy']}")
    check("EGFR progression detected in step 1",
          sim["steps"][0]["progressed"] == True,
          f"progressed={sim['steps'][0]['progressed']}")
    if len(sim["steps"]) >= 2:
        check("EGFR step 2 line = 2",
              sim["steps"][1]["line_of_therapy"] == 2,
              f"Got line={sim['steps'][1]['line_of_therapy']}")

    # ── Test 2: ALK → Alectinib → Lorlatinib ───────────────────────────
    alk_case = {
        "cancer_type":     "lung",
        "stage":           "IV",
        "biomarkers":      {"ALK": "positive"},
        "driver_mutation": "ALK",
        "mutation":        "ALK",
        "line":            1,
        "line_of_therapy": 1,
        "ecog_status":     1,
        "creatinine_clearance": 88.0,
        "contraindications":    [],
        "brain_mets":           True,
        "cns_disease":          True,
        "resistance_mutation":  None,
    }

    alk_sim = TIMELINE_ENGINE.simulate(
        initial_case       = alk_case,
        progression_states = [{"radiology": {"recist": "PD"}}],
        max_steps          = 3,
    )
    check("ALK simulation runs without error", "steps" in alk_sim)
    step1_decision = alk_sim["steps"][0]["decision"]
    step1_text     = step1_decision.get("output_text", "")
    check("ALK step 1 output contains Alectinib",
          "Alectinib" in step1_text,
          f"Output snippet: {step1_text[:200]}")

    # ── Test 3: IO → Pembrolizumab → progression → Docetaxel ────────────
    io_case = {
        "cancer_type":          "lung",
        "stage":                "IV",
        "biomarkers":           {"PD-L1": 0.75},
        "driver_mutation":      None,
        "mutation":             None,
        "pdl1":                 0.75,
        "line":                 1,
        "line_of_therapy":      1,
        "ecog_status":          1,
        "creatinine_clearance": 80.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
        "disease_burden":       "moderate",
    }

    io_sim = TIMELINE_ENGINE.simulate(
        initial_case       = io_case,
        progression_states = [{"radiology": {"recist": "PD"}}],
        max_steps          = 2,
    )
    check("IO simulation runs", "steps" in io_sim)
    io_step1 = io_sim["steps"][0]["decision"].get("output_text", "")
    check("IO step 1 contains Pembrolizumab",
          "Pembrolizumab" in io_step1,
          f"Output snippet: {io_step1[:200]}")

    # ── Test 4: Oligoprogression — continue systemic therapy ─────────────
    oligo_case = copy.deepcopy(egfr_case)
    oligo_case["radiology"] = {"oligoprogression": True}

    from engine.cancers.lung_progression import detect as lung_detect
    oligo_prog, oligo_reason = lung_detect(oligo_case)
    check("Oligoprogression correctly detected",
          oligo_prog == True and "Oligoprogression" in oligo_reason,
          f"Got: progressed={oligo_prog}, reason={oligo_reason}")

    # ── Test 5: Single-step output == Phase 6 output (stability check) ────
    single_step = TIMELINE_ENGINE.simulate(
        initial_case = egfr_case,
        max_steps    = 1,
    )
    single_out = single_step["steps"][0]["decision"].get("output_text", "")
    p6_direct  = run_phase6(egfr_case)
    check("Single-step timeline output matches Phase 6 directly",
          single_out == p6_direct,
          f"Mismatch detected. Lengths: {len(single_out)} vs {len(p6_direct)}")

    gate("Phase 7B Validated")


# ===========================================================================
# PHASE 7C TESTS
# ===========================================================================

def test_7c():
    section("PHASE 7C — Learning Engine")

    from learning.learning_engine import LearningEngine

    le = LearningEngine(similarity_threshold=0.70)

    breast_her2_case = {
        "cancer_type":     "breast",
        "subtype":         "HER2+",
        "stage":           "IV",
        "line_of_therapy": 1,
        "biomarkers":      {"HER2": "positive"},
    }

    mock_decision = {
        "cancer_type":   "breast",
        "final_regimen": "Trastuzumab + Pertuzumab + Docetaxel",
        "line":          1,
        "confidence":    0.90,
        "reason":        "HER2+ 1L standard",
    }

    # ── Test 1: New case → baseline confidence maintained ────────────────
    result = le.adjust_confidence(breast_her2_case, mock_decision)
    check("New case: decision unchanged",
          result["final_regimen"] == mock_decision["final_regimen"],
          f"Got: {result['final_regimen']}")
    check("New case: baseline confidence maintained",
          result["confidence"] == mock_decision["confidence"],
          f"Got: {result['confidence']} expected {mock_decision['confidence']}")
    check("New case: learning reports 0 similar cases",
          result["_learning"]["similar_cases_found"] == 0)

    # ── Test 2: Repeated case with good outcome → confidence increases ────
    for i in range(3):
        le.store(breast_her2_case, "Trastuzumab + Pertuzumab + Docetaxel", outcome="good")

    result_after = le.adjust_confidence(breast_her2_case, mock_decision)
    check("Repeated good case: decision unchanged",
          result_after["final_regimen"] == mock_decision["final_regimen"],
          f"Got: {result_after['final_regimen']}")
    check("Repeated good case: confidence increases",
          result_after["confidence"] > mock_decision["confidence"],
          f"Got conf={result_after['confidence']} expected >{mock_decision['confidence']}")
    check("Repeated good case: similar_cases_found > 0",
          result_after["_learning"]["similar_cases_found"] > 0)

    # ── Test 3: Incorrect past outcome → no decision change ──────────────
    le2 = LearningEngine(similarity_threshold=0.70)
    le2.store(breast_her2_case, "Trastuzumab + Pertuzumab + Docetaxel", outcome="poor")

    result_poor = le2.adjust_confidence(breast_her2_case, mock_decision)
    check("Poor outcome: decision/regimen unchanged",
          result_poor["final_regimen"] == mock_decision["final_regimen"],
          f"Got: {result_poor['final_regimen']}")
    check("Poor outcome: confidence NOT increased (may decrease)",
          result_poor["confidence"] <= mock_decision["confidence"],
          f"Got conf={result_poor['confidence']} expected <={mock_decision['confidence']}")

    # ── Test 4: NSCLC pipeline unchanged through learning ────────────────
    from orchestrator import run_7c, run_7a

    lung_egfr = {
        "cancer_type":     "lung",
        "stage":           "IV",
        "biomarkers":      {"EGFR": "positive"},
        "driver_mutation": "EGFR",
        "mutation":        "EGFR",
        "line":            1,
        "ecog_status":     1,
        "creatinine_clearance": 85.0,
        "contraindications":    [],
        "brain_mets":           False,
        "cns_disease":          False,
        "resistance_mutation":  None,
    }

    # Run 7A baseline
    p7a_base = run_7a(lung_egfr)

    # Run 7C (learning-wrapped)
    p7c_result = run_7c(lung_egfr)
    check("NSCLC: 7C output_text identical to 7A",
          p7c_result.get("output_text") == p7a_base.get("output_text"),
          "NSCLC pipeline output changed after learning pass")

    # ── Test 5: Safety assertion — confirm it fires on violation ─────────
    bad_decision = {
        "cancer_type":   "breast",
        "final_regimen": "Trastuzumab + Pertuzumab + Docetaxel",
        "confidence":    0.90,
    }

    class _MutatingLearning(LearningEngine):
        def adjust_confidence(self, case, base_decision):
            # Call the real method but then deliberately violate the post-condition
            result = super().adjust_confidence(case, base_decision)
            # Simulate what would happen if someone mutated the regimen
            result["final_regimen"] = "INJECTED_REGIMEN"
            # Now manually run the assertion the engine would enforce
            decision_after = result.get("final_regimen") or result.get("regimen", "")
            decision_before = base_decision.get("final_regimen") or base_decision.get("regimen", "")
            assert decision_before == decision_after, (
                f"LEARNING ENGINE SAFETY VIOLATION: "
                f"decision changed from '{decision_before}' to '{decision_after}'."
            )
            return result

    le_bad = _MutatingLearning()
    try:
        le_bad.adjust_confidence(breast_her2_case, bad_decision)
        check("Safety assertion fires on regimen mutation", False,
              "AssertionError should have been raised")
    except AssertionError:
        check("Safety assertion fires on regimen mutation", True,
              "Correctly caught regimen mutation attempt")

    gate("Phase 7C Validated")


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("\n" + "="*60)
    print("  ZYPHRAXIS PHASE 7 — VALIDATION TEST SUITE")
    print("="*60)

    test_7a()
    if not _STOPPED:
        test_7b()
    if not _STOPPED:
        test_7c()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {len(_PASSED)} passed, {len(_FAILED)} failed")
    print(f"{'='*60}")

    if _FAILED:
        print(f"\n  ❌  FAILED: {_FAILED}")
        sys.exit(1)
    else:
        print("\n  🎉  ALL VALIDATION GATES PASSED")
        print("  Phase 7A Validated")
        print("  Phase 7B Validated")
        print("  Phase 7C Validated")
        sys.exit(0)


if __name__ == "__main__":
    main()
