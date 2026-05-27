"""
tests/test_phase10_fixes.py — Phase 10 Integration Tests

Covers all 4 critical fixes:
  Issue 1: Missing lung regimens in catalogue
  Issue 2: Prior-therapy exclusion guard
  Issue 3: Non-lung third-line expansion
  Issue 4: PatientJourney persistence layer

Research use only. Not a licensed medical device.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# =============================================================================
# ISSUE 1: Missing Lung Regimens
# =============================================================================

class TestIssue1LungCatalogue:
    """Verify that Phase 10 lung regimens are in LUNG_TREATMENTS catalogue."""

    def _get_treatment_names(self):
        from engine.cancers.lung import LUNG_TREATMENTS
        return [t.name for t in LUNG_TREATMENTS]

    def test_lorlatinib_alk_in_catalogue(self):
        names = self._get_treatment_names()
        assert any("Lorlatinib" in n and "ALK" in n for n in names), \
            f"Lorlatinib (ALK 2L+) not found in LUNG_TREATMENTS. Got: {names}"

    def test_lorlatinib_ros1_in_catalogue(self):
        names = self._get_treatment_names()
        assert any("Lorlatinib" in n and "ROS1" in n for n in names), \
            f"Lorlatinib (ROS1 2L+) not found in LUNG_TREATMENTS."

    def test_sotorasib_kras_in_catalogue(self):
        names = self._get_treatment_names()
        assert any("Sotorasib" in n for n in names), \
            f"Sotorasib not found in LUNG_TREATMENTS."

    def test_tdxd_her2_in_catalogue(self):
        names = self._get_treatment_names()
        assert any("T-DXd" in n and "HER2" in n for n in names), \
            f"T-DXd (HER2 exon 20) not found in LUNG_TREATMENTS."

    def test_selpercatinib_ret_in_catalogue(self):
        names = self._get_treatment_names()
        assert any("Selpercatinib" in n for n in names), \
            f"Selpercatinib not found in LUNG_TREATMENTS."

    def test_amivantamab_egfr_exon20_in_catalogue(self):
        names = self._get_treatment_names()
        assert any("Amivantamab" in n for n in names), \
            f"Amivantamab not found in LUNG_TREATMENTS."

    def test_total_catalogue_expanded(self):
        from engine.cancers.lung import LUNG_TREATMENTS
        assert len(LUNG_TREATMENTS) >= 18, \
            f"Expected at least 18 lung treatments (12 Phase 9 + 6 Phase 10), got {len(LUNG_TREATMENTS)}"


# =============================================================================
# ISSUE 2: Prior-Therapy Exclusion Guard
# =============================================================================

class TestIssue2PriorTherapyGuard:
    """Verify prior therapy guard prevents duplicate recommendations."""

    def _guard(self, treatment_name, prior_therapies):
        from pipeline_integration import _prior_therapy_guard
        return _prior_therapy_guard({"name": treatment_name}, prior_therapies)

    def test_osimertinib_excluded_when_prior(self):
        is_excluded, reason = self._guard("Osimertinib 2L (T790M+)", ["Osimertinib 1L"])
        assert is_excluded, "Osimertinib should be excluded when prior Osimertinib received"
        assert reason is not None

    def test_lorlatinib_allowed_when_alectinib_prior(self):
        is_excluded, _ = self._guard("Lorlatinib (ALK 2L+)", ["Alectinib 1L"])
        assert not is_excluded, "Lorlatinib should NOT be excluded — different drug from Alectinib"

    def test_pembrolizumab_excluded_when_prior(self):
        is_excluded, _ = self._guard("Pembrolizumab monotherapy", ["Pembrolizumab + Chemotherapy"])
        assert is_excluded, "Pembrolizumab variant should be excluded when pembrolizumab already given"

    def test_empty_prior_therapies_allows_all(self):
        is_excluded, _ = self._guard("Osimertinib 1L", [])
        assert not is_excluded, "No prior therapies → nothing should be excluded"

    def test_none_prior_therapies_allows_all(self):
        is_excluded, _ = self._guard("Carboplatin + Pemetrexed", None)
        assert not is_excluded, "None prior therapies → nothing should be excluded"

    def test_case_insensitive_matching(self):
        is_excluded, _ = self._guard("osimertinib 2L (T790M+)", ["OSIMERTINIB 1L"])
        assert is_excluded, "Matching should be case-insensitive"


# =============================================================================
# ISSUE 3: Third-Line Expansion
# =============================================================================

class TestIssue3ThirdLine:
    """Verify 3L YAML entries exist in cancer-specific pathway files."""

    def _load_yaml(self, cancer_type):
        import yaml
        from pathlib import Path
        yaml_path = Path(__file__).parent.parent / "clinical" / "cancers" / cancer_type / "pathways.yaml"
        with open(yaml_path) as f:
            return yaml.safe_load(f)

    def test_breast_third_line_exists_in_yaml(self):
        data = self._load_yaml("breast")
        third_line = (
            data.get("breast", {})
            .get("metastatic", {})
            .get("third_line")
        )
        assert third_line is not None, "breast/pathways.yaml missing third_line section"

    def test_breast_her2_third_line_has_options(self):
        data = self._load_yaml("breast")
        options = (
            data["breast"]["metastatic"]["third_line"]
            .get("HER2+", {})
            .get("options", [])
        )
        assert len(options) >= 2, f"Expected >=2 HER2+ 3L options, got {len(options)}"

    def test_colorectal_third_line_exists_in_yaml(self):
        data = self._load_yaml("colorectal")
        third_line = (
            data.get("colorectal", {})
            .get("metastatic", {})
            .get("third_line")
        )
        assert third_line is not None, "colorectal/pathways.yaml missing third_line section"

    def test_colorectal_mss_third_line_has_options(self):
        data = self._load_yaml("colorectal")
        options = (
            data["colorectal"]["metastatic"]["third_line"]
            .get("MSS", {})
            .get("options", [])
        )
        assert len(options) >= 2, f"Expected >=2 MSS 3L options, got {len(options)}"

    def test_prostate_third_line_exists_in_yaml(self):
        data = self._load_yaml("prostate")
        third_line = (
            data.get("prostate", {})
            .get("metastatic", {})
            .get("third_line_CRPC")
        )
        assert third_line is not None, "prostate/pathways.yaml missing third_line_CRPC section"

    def test_prostate_third_line_has_options(self):
        data = self._load_yaml("prostate")
        options = (
            data["prostate"]["metastatic"]["third_line_CRPC"]
            .get("options", [])
        )
        assert len(options) >= 3, f"Expected >=3 prostate 3L options, got {len(options)}"


# =============================================================================
# ISSUE 4: PatientJourney Persistence Layer
# =============================================================================

class TestIssue4PatientJourney:
    """Verify PatientJourney class can create, save, and load journeys."""

    def _get_backend(self, tmp_dir="/tmp/test_journeys_phase10"):
        from patient_journey import JSONStorageBackend
        return JSONStorageBackend(tmp_dir)

    def test_import_patient_journey(self):
        from patient_journey import PatientJourney, TreatmentEpisode, JSONStorageBackend
        assert PatientJourney is not None
        assert TreatmentEpisode is not None

    def test_create_new_journey(self):
        from patient_journey import PatientJourney
        backend = self._get_backend()
        journey = PatientJourney(
            journey_id="test_p001",
            patient_demographics={"age": 65, "sex": "F", "stage": "IV"},
            storage_backend=backend,
        )
        assert journey.journey_id == "test_p001"
        assert journey.episodes == []

    def test_add_episode_to_journey(self):
        from patient_journey import PatientJourney, TreatmentEpisode
        backend = self._get_backend()
        journey = PatientJourney(
            journey_id="test_p002",
            patient_demographics={"age": 58, "sex": "M"},
            storage_backend=backend,
        )
        ep = TreatmentEpisode(
            episode_num=1,
            regimen="Osimertinib 1L",
            start_date="2024-01-15",
            end_date="2024-11-20",
            outcome="PD",
            toxicity="mild",
        )
        journey.add_episode(ep)
        assert len(journey.episodes) == 1
        assert journey.episodes[0].regimen == "Osimertinib 1L"

    def test_get_prior_therapies_from_journey(self):
        from patient_journey import PatientJourney, TreatmentEpisode
        backend = self._get_backend()
        journey = PatientJourney(
            journey_id="test_p003",
            patient_demographics={},
            storage_backend=backend,
        )
        journey.add_episode(TreatmentEpisode(episode_num=1, regimen="Osimertinib 1L",
                                             start_date="2024-01-01", end_date="2024-12-01",
                                             outcome="PD", toxicity="mild"))
        prior = journey.get_prior_therapies()
        assert "Osimertinib 1L" in prior, f"Expected 'Osimertinib 1L' in {prior}"

    def test_save_and_load_journey(self):
        import os
        from patient_journey import PatientJourney, TreatmentEpisode
        backend = self._get_backend()
        journey = PatientJourney(
            journey_id="test_p004_save_load",
            patient_demographics={"age": 72},
            storage_backend=backend,
        )
        journey.add_episode(TreatmentEpisode(episode_num=1, regimen="Lorlatinib 2L",
                                             start_date="2025-01-01", end_date="2025-06-01",
                                             outcome="PR", toxicity="moderate"))
        journey.save()

        loaded = PatientJourney.load("test_p004_save_load", backend)
        assert loaded is not None, "Journey should load after save"
        assert len(loaded.episodes) == 1
        assert loaded.episodes[0].regimen == "Lorlatinib 2L"

    def test_journey_integrate_into_pipeline(self):
        from patient_journey import PatientJourney, TreatmentEpisode, integrate_journey_into_pipeline
        backend = self._get_backend()
        journey = PatientJourney(
            journey_id="test_p005_integration",
            patient_demographics={},
            storage_backend=backend,
        )
        journey.add_episode(TreatmentEpisode(episode_num=1, regimen="Osimertinib 1L",
                                             start_date="2024-03-01", end_date="2025-01-01",
                                             outcome="PD", toxicity="mild"))
        patient = {"cancer_type": "lung", "biomarkers": {"EGFR": True}}
        enriched = integrate_journey_into_pipeline(patient, journey)
        assert "prior_therapies" in enriched, "Integration should add prior_therapies to patient dict"
        assert "Osimertinib 1L" in enriched["prior_therapies"]


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == "__main__":
    import traceback
    suites = [
        TestIssue1LungCatalogue,
        TestIssue2PriorTherapyGuard,
        TestIssue3ThirdLine,
        TestIssue4PatientJourney,
    ]
    passed = 0
    failed = 0
    for suite_cls in suites:
        suite = suite_cls()
        methods = [m for m in dir(suite) if m.startswith("test_")]
        print(f"\n{'='*60}")
        print(f"  {suite_cls.__name__}")
        print(f"{'='*60}")
        for method in methods:
            try:
                getattr(suite, method)()
                print(f"  ✓ {method}")
                passed += 1
            except Exception as exc:
                print(f"  ✗ {method}")
                print(f"    {exc}")
                failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    if failed:
        sys.exit(1)
