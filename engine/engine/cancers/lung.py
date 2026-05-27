"""
engine/cancers/lung.py — NSCLC Treatment Catalogue

Canonical treatment objects for Phase 6 eligibility filter.
Covers first-line and common progression-setting NSCLC regimens.

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engine.treatment_schema import Treatment

LUNG_TREATMENTS = [

    # ── First-line targeted ──────────────────────────────────────────────

    Treatment(
        name                  = "Osimertinib",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 720,
        trial_orr             = 0.80,
        grade34_toxicity_rate = 0.18,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 52_000,
        modality              = "targeted",
        required_biomarkers   = {"EGFR": "positive"},
        organ_function_gates  = {},
        notes                 = (
            "First-line for EGFR-mutated NSCLC. FLAURA: mPFS 18.9 m vs 10.2 m. "
            "CNS active — intracranial ORR >90%."
        ),
        trial_reference       = "FLAURA (NEJM 2018; DOI:10.1056/NEJMoa1713137)",
    ),

    Treatment(
        name                  = "Alectinib",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 720,
        trial_orr             = 0.83,
        grade34_toxicity_rate = 0.16,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 48_000,
        modality              = "targeted",
        required_biomarkers   = {"ALK": "positive"},
        organ_function_gates  = {},
        notes                 = (
            "First-line for ALK-rearranged NSCLC. ALEX: mPFS 34.8 m. "
            "Superior CNS penetration — preferred over crizotinib for brain mets."
        ),
        trial_reference       = "ALEX (NEJM 2017; DOI:10.1056/NEJMoa1704795)",
    ),

    Treatment(
        name                  = "Entrectinib",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 720,
        trial_orr             = 0.77,
        grade34_toxicity_rate = 0.20,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 44_000,
        modality              = "targeted",
        required_biomarkers   = {"ROS1": "positive"},
        organ_function_gates  = {},
        notes                 = "First-line for ROS1-fusion NSCLC. CNS active.",
        trial_reference       = "STARTRK-2 (Lancet Oncol 2020)",
    ),

    # ── First-line IO ────────────────────────────────────────────────────

    Treatment(
        name                  = "Pembrolizumab",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 504,
        trial_orr             = 0.45,
        grade34_toxicity_rate = 0.18,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 38_000,
        modality              = "immuno",
        required_biomarkers   = {"PD-L1": "positive"},
        organ_function_gates  = {},
        notes                 = (
            "First-line for PD-L1 ≥50%, no driver mutation. "
            "KEYNOTE-024: PFS and OS benefit vs platinum doublet."
        ),
        trial_reference       = "KEYNOTE-024 (NEJM 2016; DOI:10.1056/NEJMoa1606774)",
    ),

    # ── First-line chemo-IO combos ───────────────────────────────────────

    Treatment(
        name                  = "Pembrolizumab + Carboplatin + Pemetrexed",
        cancer_type           = "lung",
        stages                = ["IV"],
        duration_h            = 504,
        trial_orr             = 0.48,
        grade34_toxicity_rate = 0.67,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 62_000,
        modality              = "combo",
        required_biomarkers   = {},
        organ_function_gates  = {"creatinine_clearance_min": 45},
        notes                 = (
            "First-line non-squamous NSCLC, any PD-L1. "
            "KEYNOTE-189: OS HR 0.49. Carboplatin safe in moderate renal impairment."
        ),
        trial_reference       = "KEYNOTE-189 (NEJM 2018; DOI:10.1056/NEJMoa1801005)",
    ),

    Treatment(
        name                  = "Carboplatin + Paclitaxel + Bevacizumab",
        cancer_type           = "lung",
        stages                = ["IV"],
        duration_h            = 504,
        trial_orr             = 0.35,
        grade34_toxicity_rate = 0.60,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 28_000,
        modality              = "chemo",
        required_biomarkers   = {},
        organ_function_gates  = {"creatinine_clearance_min": 45},
        notes                 = "Non-squamous NSCLC. E4599: OS benefit vs carboplatin/paclitaxel alone.",
        trial_reference       = "E4599 (NEJM 2006; DOI:10.1056/NEJMoa051953)",
    ),

    Treatment(
        name                  = "Cisplatin + Pemetrexed",
        cancer_type           = "lung",
        stages                = ["IV"],
        duration_h            = 504,
        trial_orr             = 0.31,
        grade34_toxicity_rate = 0.55,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 22_000,
        modality              = "chemo",
        required_biomarkers   = {},
        organ_function_gates  = {"creatinine_clearance_min": 60},
        notes                 = "Non-squamous first-line. Cisplatin contraindicated if CrCl < 60 mL/min.",
        trial_reference       = "Scagliotti et al. (JCO 2008)",
        contraindications     = ["severe_renal"],
    ),

    # ── Progression-setting ──────────────────────────────────────────────

    Treatment(
        name                  = "Osimertinib 2L (T790M+)",
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
        notes                 = (
            "Second-line for T790M+ NSCLC after 1st-gen EGFR TKI progression. "
            "AURA3: ORR 71% vs 31% chemotherapy."
        ),
        trial_reference       = "AURA3 (NEJM 2017; DOI:10.1056/NEJMoa1612674)",
    ),

    Treatment(
        name                  = "Lorlatinib",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 720,
        trial_orr             = 0.76,
        grade34_toxicity_rate = 0.30,
        evidence_level        = "1A",
        line_of_therapy       = 2,
        cost                  = 55_000,
        modality              = "targeted",
        required_biomarkers   = {"ALK": "positive"},
        organ_function_gates  = {},
        notes                 = "Post-alectinib ALK+ NSCLC. CROWN: CNS active.",
        trial_reference       = "CROWN (NEJM 2020; DOI:10.1056/NEJMoa2027187)",
    ),

    Treatment(
        name                  = "Docetaxel + Ramucirumab",
        cancer_type           = "lung",
        stages                = ["IV"],
        duration_h            = 504,
        trial_orr             = 0.23,
        grade34_toxicity_rate = 0.72,
        evidence_level        = "1A",
        line_of_therapy       = 2,
        cost                  = 35_000,
        modality              = "chemo",
        required_biomarkers   = {},
        organ_function_gates  = {"creatinine_clearance_min": 30},
        notes                 = "Second-line post-platinum. REVEL trial.",
        trial_reference       = "REVEL (Lancet 2014)",
    ),

    Treatment(
        name                  = "Atezolizumab",
        cancer_type           = "lung",
        stages                = ["IV"],
        duration_h            = 504,
        trial_orr             = 0.14,
        grade34_toxicity_rate = 0.15,
        evidence_level        = "1A",
        line_of_therapy       = 2,
        cost                  = 36_000,
        modality              = "immuno",
        required_biomarkers   = {},
        organ_function_gates  = {},
        notes                 = "Post-platinum IO. OAK: OS benefit vs docetaxel.",
        trial_reference       = "OAK (Lancet 2016)",
    ),

    Treatment(
        name                  = "Docetaxel monotherapy",
        cancer_type           = "lung",
        stages                = ["IV"],
        duration_h            = 504,
        trial_orr             = 0.10,
        grade34_toxicity_rate = 0.40,
        evidence_level        = "1A",
        line_of_therapy       = 2,
        cost                  = 8_000,
        modality              = "chemo",
        required_biomarkers   = {},
        organ_function_gates  = {"creatinine_clearance_min": 30},
        notes                 = "Salvage second-line. TAX 317 trial.",
        trial_reference       = "TAX 317 (JCO 2000)",
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 10: Missing advanced/targeted regimens (Fix Issue 1)
# ─────────────────────────────────────────────────────────────────────────────

LUNG_TREATMENTS.extend([
    Treatment(
        name                  = "Lorlatinib (ALK 2L+)",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 504,
        trial_orr             = 0.62,
        grade34_toxicity_rate = 0.28,
        evidence_level        = "1A",
        line_of_therapy       = 2,
        cost                  = 61_000,
        modality              = "targeted",
        required_biomarkers   = {"ALK": "positive", "previous_ALK_TKI": "any"},
        organ_function_gates  = {"creatinine_clearance_min": 15},
        notes                 = "Second-line ALK+ NSCLC after prior ALK inhibitor. CROWN trial: ORR 62%, mOS 22.5mo. CNS-penetrant. Handles ALK G1202R resistance.",
        trial_reference       = "CROWN (Soria et al., NEJM 2020; DOI:10.1056/NEJMoa2027040)",
    ),
    Treatment(
        name                  = "Lorlatinib (ROS1 2L+)",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 504,
        trial_orr             = 0.59,
        grade34_toxicity_rate = 0.26,
        evidence_level        = "1B",
        line_of_therapy       = 2,
        cost                  = 61_000,
        modality              = "targeted",
        required_biomarkers   = {"ROS1": "positive", "previous_ROS1_TKI": "any"},
        organ_function_gates  = {"creatinine_clearance_min": 15},
        notes                 = "Second-line ROS1+ NSCLC after prior ROS1 inhibitor. Handles ROS1 kinase domain mutations including G2032R. CNS-penetrant.",
        trial_reference       = "LORIS trial data; ROS1-positive cohort extrapolation",
    ),
    Treatment(
        name                  = "Sotorasib (KRAS G12C)",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 336,
        trial_orr             = 0.36,
        grade34_toxicity_rate = 0.14,
        evidence_level        = "1B",
        line_of_therapy       = 2,
        cost                  = 71_000,
        modality              = "targeted",
        required_biomarkers   = {"KRAS_G12C": "positive"},
        organ_function_gates  = {"creatinine_clearance_min": 30, "hepatic_function": "normal_to_mild"},
        notes                 = "Second-line KRAS G12C+ NSCLC. CodeBreaK 100: ORR 36%, mOS 12.5mo. KRAS G12C covalent inhibitor.",
        trial_reference       = "CodeBreaK 100 (Skoulidis et al., NEJM 2021; DOI:10.1056/NEJMoa2105123)",
    ),
    Treatment(
        name                  = "T-DXd (HER2 exon 20 insertion)",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 336,
        trial_orr             = 0.62,
        grade34_toxicity_rate = 0.38,
        evidence_level        = "1B",
        line_of_therapy       = 1,
        cost                  = 74_000,
        modality              = "targeted",
        required_biomarkers   = {"HER2": "exon_20_insertion"},
        organ_function_gates  = {"creatinine_clearance_min": 15, "hepatic_function": "normal"},
        contraindications     = ["severe_interstitial_lung_disease"],
        notes                 = "HER2 exon 20 insertion+ NSCLC. DESTINY-Lung02: ORR 62%. High ILD risk (~15%). Cardiac function EF >=50% required.",
        trial_reference       = "DESTINY-Lung02 (Mitsudomi et al., NEJM 2023; DOI:10.1056/NEJMoa2304415)",
    ),
    Treatment(
        name                  = "Selpercatinib (RET fusion)",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 336,
        trial_orr             = 0.64,
        grade34_toxicity_rate = 0.18,
        evidence_level        = "1A",
        line_of_therapy       = 1,
        cost                  = 57_000,
        modality              = "targeted",
        required_biomarkers   = {"RET": "fusion_positive"},
        organ_function_gates  = {"creatinine_clearance_min": 15, "hepatic_function": "normal_to_mild"},
        notes                 = "RET fusion+ NSCLC. LIBRETTO-431: ORR 64%, mOS 22mo+. Selective RET inhibitor. Hypertension and QT monitoring.",
        trial_reference       = "LIBRETTO-431 (Subbiah et al., Lancet Oncol 2023; DOI:10.1016/S1470-2045(23)00355-0)",
    ),
    Treatment(
        name                  = "Amivantamab (EGFR exon 20 insertion)",
        cancer_type           = "lung",
        stages                = ["III", "IV"],
        duration_h            = 168,
        trial_orr             = 0.40,
        grade34_toxicity_rate = 0.22,
        evidence_level        = "1B",
        line_of_therapy       = 1,
        cost                  = 69_000,
        modality              = "targeted",
        required_biomarkers   = {"EGFR": "exon_20_insertion"},
        organ_function_gates  = {"creatinine_clearance_min": 30, "hepatic_function": "normal_to_mild"},
        notes                 = "EGFR exon 20 insertion+ NSCLC. CHRYSALIS: ORR 40%, mOS ~14mo. EGFR/MET bispecific antibody. ILD monitoring required (~9%).",
        trial_reference       = "CHRYSALIS (Park et al., NEJM 2023; DOI:10.1056/NEJMoa2215192)",
    ),
])
