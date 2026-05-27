# Zyphraxis Phase 6 — Clinical Decision Pipeline

Research use only. Not a licensed medical device.

## Quick Start

```bash
pip install -r requirements.txt

# Run full validation suite (15 tests)
python tests/test_phase6_full.py

# Run example patient
python main.py egfr_firstline
python main.py t790m_progression
python main.py alk_brain_mets
```

## Pipeline

```
Patient dict
    → Eligibility Filter (biomarker gates, renal gates, EGFR/IO exclusion)
    → Apollo Mode      (fast conservative single-pick)
    → Manhattan Mode   (deep efficacy-ranked multi-option)
    → Hybrid Engine    (arbitrates → final_regimen + confidence)
    → Justification    (why_selected, why_superior, safety_warnings)
    → Formatted output
```

## Structure

```
zyphraxis_phase6/
├── clinical/
│   ├── policy_engine.py       # Phase 6A: guideline option universe
│   ├── constraint_engine.py   # Phase 6A: organ/marrow/CNS safety filter
│   ├── apollo_mode.py         # Phase 6B: fast decision engine
│   ├── manhattan_mode.py      # Phase 6B: deep ranked evaluation
│   └── pathways.yaml          # NSCLC policy catalogue
├── engine/
│   ├── hybrid_engine.py       # Phase 6C: arbitration
│   ├── justification_engine.py # Phase 6C: audit + explanation
│   ├── treatment_schema.py    # Treatment dataclass
│   └── cancers/lung.py        # NSCLC treatment catalogue
├── tests/
│   └── test_phase6_full.py    # Master 15-test suite
├── pipeline_integration.py    # Entry point for run_phase6()
├── main.py                    # CLI runner
└── requirements.txt
```

## Test Cases Covered

| ID  | Scenario                              | Key Assertion                         |
|-----|---------------------------------------|---------------------------------------|
| 6A-1| EGFR+ + PD-L1 75%                    | Osimertinib safe; IO excluded         |
| 6A-2| Severe renal impairment               | Cisplatin blocked; carboplatin safe   |
| 6A-3| Marrow suppression                    | All chemo blocked                     |
| 6A-4| Brain mets + EGFR                     | cns_coverage tag; non-CNS warned      |
| 6A-5| All constraints extreme               | No crash; fallback warning            |
| 6B-1| Simple EGFR                           | Apollo == Manhattan rank-1            |
| 6B-2| Complex no-driver                     | Manhattan multi; Apollo single pick   |
| 6B-3| T790M+ progression                    | Both engines → Osimertinib T790M+     |
| 6B-4| EGFR + brain mets                     | CNS-active prioritised                |
| 6B-5| High burden PD-L1 60%                 | Chemo-IO > IO monotherapy             |
| 6C-1| EGFR+ PD-L1 70%                      | Osimertinib; IO justification         |
| 6C-2| PD-L1 75% no driver                  | Pembrolizumab selected                |
| 6C-3| T790M+ line 2                         | Osimertinib 2L; T790M warning         |
| 6C-4| ALK+ brain mets                       | Alectinib; CNS warning                |
| 6C-5| CrCl 22 (severe renal)               | Cisplatin excluded; renal warning     |
