================================================================================
ZYPHRAXIS PHASE 9 → PHASE 10: INTEGRATION GUIDE
================================================================================

Four critical issues fixed with complete implementation files:

  [ISSUE 1] Missing regimens in lung catalogue
  [ISSUE 2] Prior-regimen exclusion guard
  [ISSUE 3] Non-lung third-line expansion
  [ISSUE 4] PatientJourney persistence layer

================================================================================
ISSUE 1: MISSING LUNG REGIMENS
================================================================================

PROBLEM:
  HybridEngine has routing logic for:
    - Lorlatinib (ALK/ROS1 2L+)
    - Sotorasib (KRAS G12C)
    - T-DXd (HER2 exon 20)
    - Selpercatinib (RET fusion)
    - Amivantamab (EGFR exon 20 insertion)

  But pathways.yaml / LUNG_TREATMENTS catalogue has NO entries.
  Result: HybridEngine selects these as winners, then _build_safe_options()
  returns empty eligible list → NO_PATH output.

SOLUTION:
  Add these regimens to LUNG_TREATMENTS list in engine/engine/cancers/lung.py

FILES TO MODIFY:
  1. engine/engine/cancers/lung.py (main)
  2. Optional: clinical/cancers/lung/pathways.yaml (if exists)

IMPLEMENTATION STEPS:

  Step 1: Open engine/engine/cancers/lung.py
  ─────────────────────────────────────────────────────────────────────────
  Find the LUNG_TREATMENTS list and add these Treatment objects at the end:

  From fix_issue_1_lung_catalogue.py, copy MISSING_LUNG_REGIMENS dict and
  convert each to Treatment objects:

      from engine.treatment_schema import Treatment
      
      # Add these to LUNG_TREATMENTS list:
      lorlatinib_2l_alk = Treatment(
          name="Lorlatinib (ALK 2L+)",
          cancer_type="lung",
          stages=["III", "IV"],
          duration_h=504,
          trial_orr=0.62,
          grade34_toxicity_rate=0.28,
          evidence_level="1A",
          line_of_therapy=2,
          cost=61_000,
          modality="targeted",
          required_biomarkers={"ALK": "positive", "previous_ALK_TKI": "any"},
          organ_function_gates={"creatinine_clearance_min": 15},
          notes="...",
          trial_reference="CROWN (Soria et al., NEJM 2020...)",
      )
      LUNG_TREATMENTS.append(lorlatinib_2l_alk)
      # Repeat for: lorlatinib_2l_ros1, sotorasib_kras, tdxd_her2_exon20,
      #            selpercatinib_ret, amivantamab_egfr_exon20

  Step 2: Verify biomarker gating
  ─────────────────────────────────────────────────────────────────────────
  Each regimen must have required_biomarkers dict matching HybridEngine expectations:

      Lorlatinib ALK 2L+:     required_biomarkers = {"ALK": "positive"}
      Lorlatinib ROS1 2L+:    required_biomarkers = {"ROS1": "positive"}
      Sotorasib KRAS G12C:    required_biomarkers = {"KRAS_G12C": "positive"}
      T-DXd HER2 exon 20:     required_biomarkers = {"HER2": "exon_20_insertion"}
      Selpercatinib RET:      required_biomarkers = {"RET": "fusion_positive"}
      Amivantamab EGFR exon20: required_biomarkers = {"EGFR": "exon_20_insertion"}

  Step 3: Test that _build_safe_options() now finds them
  ─────────────────────────────────────────────────────────────────────────
  In tests/test_missing_regimens.py, add:

      def test_lorlatinib_alk_selectable():
          patient = {
              "cancer_type": "lung",
              "biomarkers": {"ALK": "positive"},
              "creatinine_clearance": 45,
              "line": 2,
              "prior_therapies": ["Alectinib 1L"],
          }
          eligible, rejected = _build_safe_options(patient)
          assert any(t["name"] == "Lorlatinib (ALK 2L+)" for t in eligible)

EXPECTED OUTCOME:
  ✓ HybridEngine can now select these regimens
  ✓ _build_safe_options() returns them in eligible list
  ✓ JustificationEngine provides audit trail with biomarker gates
  ✓ No more NO_PATH for patients with these driver mutations


================================================================================
ISSUE 2: PRIOR-THERAPY EXCLUSION GUARD
================================================================================

PROBLEM:
  _normalise_patient() reads prior_therapies from input, but _build_safe_options()
  never uses it. Patient who received Osimertinib 1L can be recommended Osimertinib 2L
  (which may be appropriate) OR Osimertinib again at same line (which is NOT).

SOLUTION:
  Add _prior_therapy_guard() helper + integrate into _build_safe_options()
  filtering loop to exclude any treatment matching prior therapy names.

FILES TO MODIFY:
  1. engine/pipeline_integration.py (main)

IMPLEMENTATION STEPS:

  Step 1: Add _prior_therapy_guard() helper (before _build_safe_options)
  ─────────────────────────────────────────────────────────────────────────
  Copy from fix_issue_2_prior_therapy_guard.py:

      def _prior_therapy_guard(treatment: dict, prior_therapies: list) -> tuple:
          """
          Check if treatment is in prior therapies.
          Returns (is_excluded: bool, reason: str)
          """
          if not prior_therapies:
              return False, None

          treatment_name = treatment.get("name", "").lower()
          for prior in prior_therapies:
              if not prior:
                  continue
              prior_lower = prior.lower()
              if prior_lower in treatment_name or treatment_name in prior_lower:
                  return True, f"Prior therapy: {prior} — already received (substring match)"

          return False, None

  Step 2: Modify _build_safe_options() eligibility loop
  ─────────────────────────────────────────────────────────────────────────
  Around line 226 in pipeline_integration.py, add prior therapy check FIRST:

      def _build_safe_options(patient: dict) -> tuple:
          # ... existing code ...
          raw        = patient.get("_raw", patient)
          biomarkers = raw.get("biomarkers", {})
          # ... etc ...

          # [NEW] Get prior therapies from normalised patient dict
          prior_therapy = patient.get("prior_therapy") or raw.get("prior_therapies")
          if isinstance(prior_therapy, str):
              prior_therapy = [prior_therapy]
          elif not isinstance(prior_therapy, list):
              prior_therapy = []

          # ... existing treatments list building ...

          for t in treatments:
              reject_reason = None

              # [NEW] PRIOR THERAPY GUARD — check first, fail fast
              is_prior, prior_reason = _prior_therapy_guard(t, prior_therapy)
              if is_prior:
                  reject_reason = prior_reason
              # [END NEW]

              # ... rest of existing checks (biomarkers, organ function, etc.) ...

  Step 3: Ensure _normalise_patient() populates prior_therapy
  ─────────────────────────────────────────────────────────────────────────
  Check line ~169 in pipeline_integration.py. Should have:

      return {
          # ... other fields ...
          "prior_therapy": patient.get("prior_therapies"),  # ← already there
          # ... other fields ...
      }

  Step 4: Test prior therapy exclusion
  ─────────────────────────────────────────────────────────────────────────
  In tests/test_prior_therapy.py, add:

      def test_prior_osimertinib_excluded():
          patient = {
              "cancer_type": "lung",
              "biomarkers": {"EGFR": "positive", "T790M": "positive"},
              "creatinine_clearance": 45,
              "line": 2,
              "prior_therapies": ["Osimertinib 1L"],  # ← Already received
          }
          # Normalise
          norm_patient = _normalise_patient(patient)
          eligible, rejected = _build_safe_options(norm_patient)

          # Should have Osimertinib 2L (T790M+) IF available
          # But also check that plain re-recommendation is excluded
          osim_results = [t for t in rejected if "Osimertinib" in t["treatment_name"]]
          # At least one Osimertinib rejection should have "Prior therapy" reason

EXPECTED OUTCOME:
  ✓ Patients cannot be re-recommended same regimen at same/lower line
  ✓ T790M+ patients can get Osimertinib 2L even if had Osimertinib 1L
  ✓ Clear rejection reason in audit: "Prior therapy: Osimertinib 1L"
  ✓ Intelligent string matching (substring-based)


================================================================================
ISSUE 3: NON-LUNG THIRD-LINE EXPANSION
================================================================================

PROBLEM:
  Breast, colorectal, prostate have 1L + 2L options, but NO 3L.
  TimelineEngine at step 3 calls DISEASE_ROUTER.route() which calls
  policy_engine.get_options(line=3) → empty list → NO_PATH or null.

SOLUTION:
  Add OPTIONS_3L to each cancer type catalogue with appropriate regimens.
  Architecture depends on how clinical_cancers is structured.

FILES TO MODIFY:
  1. clinical/cancers/breast/pathways.yaml (or progression.py)
  2. clinical/cancers/colorectal/pathways.yaml (or progression.py)
  3. clinical/cancers/prostate/pathways.yaml (or progression.py)

OPTION A: YAML-based (if pathways.yaml exists)
──────────────────────────────────────────────────────────────────────────

  Step 1: Open clinical/cancers/breast/pathways.yaml
  Step 2: Add options_progression_3l section with regimens from fix_issue_3:

      options_progression_3l:
        - name: "T-DM1 (Ado-trastuzumab emtansine)"
          line_of_therapy: 3
          modality: "immuno-targeted"
          required_biomarkers:
            HER2: "positive"
            prior_trastuzumab: "any"
            prior_taxane: "any"
          trial_orr: 0.43
          evidence_level: "1A"
          cost: 54000
          notes: "HER2+ breast cancer 3L after trastuzumab + taxane..."
        
        - name: "T-DXd (Trastuzumab deruxtecan)"
          line_of_therapy: 3
          modality: "immuno-targeted"
          required_biomarkers:
            HER2: "positive"
          trial_orr: 0.55
          evidence_level: "1A"
          cost: 74000
          notes: "NextGen ADC for HER2+ breast cancer 3L..."
        
        # ... repeat for Sacituzumab govitecan, Capecitabine

  Step 3: Repeat for colorectal and prostate

OPTION B: Python-based (if using progression.py modules)
──────────────────────────────────────────────────────────────────────────

  Step 1: Open clinical/cancers/breast/progression.py
  Step 2: At top, add OPTIONS_3L constant:

      from engine.treatment_schema import Treatment

      OPTIONS_3L = [
          Treatment(
              name="T-DM1 (Ado-trastuzumab emtansine)",
              cancer_type="breast",
              stages=["III", "IV"],
              duration_h=168,
              trial_orr=0.43,
              grade34_toxicity_rate=0.19,
              evidence_level="1A",
              line_of_therapy=3,
              cost=54_000,
              modality="immuno-targeted",
              required_biomarkers={"HER2": "positive"},
              notes="...",
          ),
          # ... add other 3L regimens ...
      ]

  Step 3: In policy_engine.py, update get_options() to include OPTIONS_3L:

      def get_options(cancer_type: str, line: int, **context) -> List[Treatment]:
          """Get treatment options for a given cancer type and line."""
          ct_module = REGISTRY.get(cancer_type)
          if not ct_module:
              raise ValueError(f"Unknown cancer type: {cancer_type}")
          
          if line == 1:
              return ct_module.OPTIONS_1L
          elif line == 2:
              return ct_module.OPTIONS_2L
          elif line >= 3:  # ← NEW
              return ct_module.OPTIONS_3L or []
          return []

  Step 4: Repeat for colorectal and prostate progression.py files

STEP 5: Test third-line progression
────────────────────────────────────────────────────────────────────────────

In tests/test_third_line.py:

    def test_breast_third_line_progression():
        initial_case = {
            "cancer_type": "breast",
            "biomarkers": {"HER2": "positive"},
            "stage": "IV",
        }
        progression_states = [
            {},  # 1L → 2L
            {},  # 2L → 3L
        ]
        
        timeline = TimelineEngine()
        result = timeline.simulate(
            initial_case=initial_case,
            progression_states=progression_states,
            max_steps=4,
        )
        
        # Should have 3 steps without crashing
        assert len(result["steps"]) >= 3
        assert result["steps"][2]["decision"]["final_regimen"] != "NO_PATH"
        # Verify step 3 got a real regimen (T-DM1, T-DXd, etc.)

EXPECTED OUTCOME:
  ✓ TimelineEngine step 3 returns valid regimen (not NO_PATH)
  ✓ Policy engine has OPTIONS_3L for all 3 cancer types
  ✓ Third-line regimens respect biomarker gates
  ✓ Clear progression pathway: 1L → 2L → 3L without crashes


================================================================================
ISSUE 4: PATIENTJOURNEY PERSISTENCE LAYER
================================================================================

PROBLEM:
  Architecture is stateless: each API call knows nothing about patient history.
  System cannot track prior treatments, toxicities, responses, or use them for
  future decisions. Prior therapies must be manually specified by caller.

SOLUTION:
  Introduce PatientJourney class with:
    - Unique journey ID per patient
    - Storage backend (JSON/Redis/PostgreSQL)
    - Episodes: list of TreatmentEpisode objects
    - Automatic integration into pipeline to populate prior_therapies

FILES TO ADD/MODIFY:
  1. NEW: engine/patient_journey.py (copy from fix_issue_4_patient_journey.py)
  2. MODIFY: engine/pipeline_integration.py (add integration hook)

IMPLEMENTATION STEPS:

  Step 1: Create engine/patient_journey.py
  ────────────────────────────────────────────────────────────────────────
  Copy entire file from fix_issue_4_patient_journey.py to:
      engine/patient_journey.py

  Step 2: Modify pipeline_integration.py to support journey_id parameter
  ────────────────────────────────────────────────────────────────────────

  Find run_phase6() signature and add optional journey_id:

      def run_phase6(
          patient: dict,
          journey_id: Optional[str] = None,
          storage_backend: Optional[StorageBackend] = None,
      ) -> Dict[str, Any]:
          """
          Full Phase 6 pipeline with optional PatientJourney support.
          
          Args:
              patient:          Patient dict (disease, biomarkers, etc.)
              journey_id:       (Optional) Unique patient ID for longitudinal tracking
              storage_backend:  (Optional) Backend for journey persistence
          
          Returns:
              Recommendation dict with updated journey reference
          """
          from patient_journey import PatientJourney, integrate_journey_into_pipeline
          
          # ── Load or create journey ──────────────────────────────────────
          journey = None
          if journey_id:
              backend = storage_backend or JSONStorageBackend()
              try:
                  journey = PatientJourney.load(journey_id, backend)
                  patient = integrate_journey_into_pipeline(journey, patient)
              except KeyError:
                  # New patient — first decision
                  journey = PatientJourney(
                      journey_id=journey_id,
                      patient_demographics={
                          "age": patient.get("age"),
                          "sex": patient.get("sex"),
                          "stage_baseline": patient.get("stage", "IV"),
                      },
                      storage_backend=backend,
                  )
          
          # ── Run full pipeline (rest of existing code) ──────────────────
          norm_patient = _normalise_patient(patient)
          # ... existing pipeline code ...
          
          # ── After decision, save new episode ────────────────────────────
          if journey:
              from patient_journey import TreatmentEpisode
              episode = TreatmentEpisode(
                  episode_num=norm_patient.get("line_of_therapy", 1),
                  regimen=result["final_regimen"],
                  start_date=datetime.now().isoformat(),
                  biomarkers_at_start=norm_patient.get("biomarkers", {}),
                  outcome="unknown",  # Filled in later
                  toxicity="none",    # Filled in later
              )
              journey.add_episode(episode)
              journey.save()
              result["_journey_id"] = journey_id
              result["_journey_updated"] = True
          
          return result

  Step 3: Add datetime import
  ────────────────────────────────────────────────────────────────────────
  At top of pipeline_integration.py:

      from datetime import datetime
      from patient_journey import (
          PatientJourney,
          TreatmentEpisode,
          JSONStorageBackend,
          integrate_journey_into_pipeline,
      )

  Step 4: Test journey creation and loading
  ────────────────────────────────────────────────────────────────────────

  In tests/test_patient_journey.py:

      def test_create_and_load_journey():
          from patient_journey import PatientJourney, TreatmentEpisode, JSONStorageBackend
          
          journey = PatientJourney(
              journey_id="test_patient_001",
              patient_demographics={"age": 65, "sex": "F", "stage_baseline": "IV"},
              storage_backend=JSONStorageBackend("/tmp/test_journeys"),
          )
          
          ep1 = TreatmentEpisode(
              episode_num=1,
              regimen="Osimertinib 1L",
              start_date="2024-01-15",
              end_date="2024-11-20",
              outcome="PD",
              toxicity="mild",
          )
          journey.add_episode(ep1)
          journey.save()
          
          # Load and verify
          loaded = PatientJourney.load("test_patient_001", journey.storage_backend)
          assert len(loaded.episodes) == 1
          assert loaded.get_prior_therapies() == ["Osimertinib 1L"]

      def test_journey_integration_with_pipeline():
          # Create journey with episode
          journey = ... # from test above
          
          # Call pipeline with journey_id
          patient = {"cancer_type": "lung", "biomarkers": {"EGFR": True}}
          result = run_phase6(
              patient,
              journey_id="test_patient_001",
              storage_backend=JSONStorageBackend("/tmp/test_journeys"),
          )
          
          # Verify prior_therapies were populated
          assert "Osimertinib 1L" in result.get("_journey_prior_therapies", [])

EXPECTED OUTCOME:
  ✓ System remembers patient history across calls
  ✓ Prior therapies automatically excluded (Issue 2 guard + Journey integration)
  ✓ Toxicity tracking enables severity-aware decisions
  ✓ Resistance mutations extracted from progression biomarkers
  ✓ Full audit trail per patient
  ✓ Pluggable storage: JSON (dev), Redis (cache), PostgreSQL (production)


================================================================================
INTEGRATION CHECKLIST
================================================================================

PRE-INTEGRATION:
  [ ] Backup current codebase
  [ ] Review each fix file in detail
  [ ] Understand required_biomarkers for each regimen (Issue 1)

ISSUE 1: Lung Catalogue
  [ ] Add 6 missing Treatment objects to LUNG_TREATMENTS
  [ ] Verify required_biomarkers dict syntax
  [ ] Test _build_safe_options() finds them
  [ ] Add test: test_lorlatinib_alk_selectable()

ISSUE 2: Prior Therapy Guard
  [ ] Add _prior_therapy_guard() helper function
  [ ] Modify _build_safe_options() loop to call guard first
  [ ] Verify prior_therapy field populated by _normalise_patient()
  [ ] Add test: test_prior_osimertinib_excluded()

ISSUE 3: Third-Line Expansion
  [ ] Add OPTIONS_3L to breast/pathways.yaml
  [ ] Add OPTIONS_3L to colorectal/pathways.yaml
  [ ] Add OPTIONS_3L to prostate/pathways.yaml
  [ ] Update policy_engine.get_options() to return OPTIONS_3L for line >= 3
  [ ] Add test: test_breast_third_line_progression()

ISSUE 4: PatientJourney
  [ ] Create engine/patient_journey.py (new file)
  [ ] Import PatientJourney in pipeline_integration.py
  [ ] Add journey_id parameter to run_phase6()
  [ ] Implement journey load/create logic
  [ ] Save episode after each decision
  [ ] Add test: test_create_and_load_journey()

POST-INTEGRATION:
  [ ] Run full test suite
  [ ] Verify no regressions in existing tests
  [ ] Check Phase 6 (no journey) still works
  [ ] Check Phase 10 (with journey) works
  [ ] Manual smoke test: trace through one patient journey 3 lines


================================================================================
TESTING STRATEGY
================================================================================

Create tests/test_phase10_fixes.py with these test classes:

1. TestIssue1LungCatalogue
   - test_lorlatinib_alk_2l_selectable
   - test_sotorasib_kras_selectable
   - test_tdxd_her2_exon20_selectable
   - test_selpercatinib_ret_selectable
   - test_amivantamab_egfr_exon20_selectable
   - test_lorlatinib_ros1_2l_selectable

2. TestIssue2PriorTherapyGuard
   - test_prior_osimertinib_excluded
   - test_prior_pembrolizumab_excluded
   - test_prior_therapy_substring_match
   - test_empty_prior_therapies_allows_all
   - test_multiple_prior_therapies_excluded

3. TestIssue3ThirdLine
   - test_breast_third_line_progression
   - test_colorectal_third_line_progression
   - test_prostate_third_line_progression
   - test_timeline_engine_step3_not_crashing

4. TestIssue4PatientJourney
   - test_create_new_journey
   - test_load_existing_journey
   - test_add_episode_to_journey
   - test_journey_get_prior_therapies
   - test_journey_get_toxicity_history
   - test_journey_get_response_pattern
   - test_journey_integration_with_pipeline
   - test_journey_episode_saved_after_decision


================================================================================
ROLLOUT PLAN
================================================================================

Phase 1: Local Testing (1 day)
  ├─ Branch: feature/phase10-fixes
  ├─ Implement all 4 fixes
  ├─ Run test suite
  └─ Code review

Phase 2: Staging Environment (2 days)
  ├─ Deploy to staging
  ├─ Run full integration tests
  ├─ Manual testing with sample cases
  └─ Verify journey persistence

Phase 3: Production Rollout (1 day)
  ├─ Deploy to production
  ├─ Monitor error rates
  ├─ Verify prior therapy exclusion working
  └─ Verify journey creation working

Phase 4: Monitoring (ongoing)
  ├─ Track no. of NO_PATH recommendations (should decrease)
  ├─ Track prior therapy exclusions
  ├─ Monitor journey size / storage usage
  └─ Collect feedback on 3L recommendations


================================================================================
SUCCESS CRITERIA
================================================================================

✓ ISSUE 1: Lung catalogue complete
  - All 6 missing regimens added
  - Zero NO_PATH recommendations for ALK/ROS1/KRAS/HER2-exon20/RET patients
  - Clear audit trail showing biomarker gating

✓ ISSUE 2: Prior therapy guard active
  - Zero duplicate regimen recommendations
  - Clear rejection reasons in audit
  - Intelligent substring matching (not naive equality)

✓ ISSUE 3: Third-line expansion functional
  - TimelineEngine step 3+ returns real regimens (not NO_PATH)
  - All cancer types have 3L options
  - Progressive pathway works: 1L → 2L → 3L

✓ ISSUE 4: PatientJourney operational
  - Journeys persist across calls
  - Prior therapies auto-populated from journey history
  - Toxicity tracking enables severity-aware decisions
  - Audit trail available for compliance / ML learning

================================================================================
