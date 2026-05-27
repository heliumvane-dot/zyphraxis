# Zyphraxis — Clinical AI Copilot for Oncologists — Phase 10
> Research use only. Not a licensed medical device.

---

## 🚀 Phase 10 — What's New

Phase 10 resolves 4 critical issues identified during Phase 9 validation:

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 1 | Missing advanced lung regimens in catalogue | 30-40% of lung patients got NO_PATH | Added 6 targeted regimens (Lorlatinib ALK/ROS1, Sotorasib, T-DXd, Selpercatinib, Amivantamab) |
| 2 | Prior-therapy exclusion guard missing | Patients could be re-recommended same drug | Added `_prior_therapy_guard()` with substring matching in `pipeline_integration.py` |
| 3 | No 3L options for breast/colorectal/prostate | TimelineEngine crashed or returned NO_PATH at step 3 | Added third-line regimens to all three cancer YAML pathways (14 total) |
| 4 | Stateless architecture — no patient history | No audit trail, no longitudinal context | Introduced `PatientJourney` class with pluggable storage (JSON/Redis/PostgreSQL) |

**Expected improvements:**
- NO_PATH rate: ~15-20% → ~3-5%
- Duplicate therapy recommendations: ~5-10% → <1%
- 3L recommendation coverage: 0% → 30-40%
- Full audit trail: 100% of decisions traceable via PatientJourney

---

## 📁 Project Structure

```
Zyphraxis_Project/
├── README.md                        ← You are here
├── chatbot/
│   ├── zyphraxis_phase8.html        ← Open this in browser to use the chatbot UI
│   └── zyphraxis_phase8_server.py   ← Run this first to start the backend server
└── engine/                          ← Phase 7 clinical decision engine (do not modify)
    ├── pipeline_integration.py      ← Main entry point: run_phase6(patient)
    ├── requirements.txt             ← Python dependencies
    ├── clinical/                    ← Policy, constraint, Apollo & Manhattan modes
    │   └── cancers/                 ← Breast, colorectal, prostate modules
    ├── engine/                      ← Hybrid engine, justification, treatment schema
    │   └── cancers/                 ← Lung cancer decision logic
    ├── router/                      ← Routes cases to correct cancer module
    ├── learning/                    ← Learning engine
    ├── timeline/                    ← Timeline engine
    ├── core/                        ← Cancer registry
    ├── orchestrator.py              ← Phase 7 orchestration layer
    └── tests/                       ← Test suite (pytest)
```

---

## ⚙️ How It Works

1. Doctor describes patient in plain English in the chatbot UI
2. Claude API parses the text into a structured patient schema
3. The Phase 7 engine runs the full pipeline:
   - **Apollo Mode** — fast, conservative guideline pick
   - **Manhattan Mode** — deep ranked evaluation
   - **Hybrid Engine** — arbitrates between the two
   - **Justification Engine** — generates audit trail & explanation
4. Claude API formats the engine output for display
5. Doctor sees structured recommendation with confidence score & safety flags

---

## 🚀 How to Run

### Step 1 — Install Python dependencies
```bash
pip install flask flask-cors pydantic pyyaml
```

### Step 2 — Start the backend server
```bash
cd chatbot
python zyphraxis_phase8_server.py
```
You should see: `Running on http://127.0.0.1:7845`
**Keep this terminal window open.**

### Step 3 — Open the chatbot
Double-click `chatbot/zyphraxis_phase8.html` in your file explorer.
It opens in your browser like a website.

### Step 4 — Enter API key
Paste your Anthropic API key (`sk-ant-...`) in the top-right field.

### Step 5 — Try a demo case
Type in the chat:
```
Stage IV NSCLC, EGFR positive, first line, ECOG 1, CrCl 85
```

---

## 🔌 API Endpoints (Phase 8 Server)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/run`   | POST   | Run engine with patient JSON |
| `/health`| GET    | Health check |

**Example `/run` payload:**
```json
{
  "cancer_type": "lung",
  "stage": "IV",
  "biomarkers": { "EGFR": "positive" },
  "creatinine_clearance": 85,
  "line": 1,
  "ecog_status": 1
}
```

---

## 🧬 Supported Cancer Types
- **Lung** (NSCLC) — most complete, all biomarkers supported
- **Breast**
- **Colorectal**
- **Prostate**

---

## ⚠️ Important Notes
- The chatbot UI requires an **Anthropic API key** for natural language parsing
- The backend server must be running **before** opening the HTML file
- All recommendations require **oncologist review and authority**
- SAF (Safety Arbitration Framework) safeguards cannot be bypassed

---

## 🆕 Phase 10 File Changes

```
engine/
├── engine/cancers/lung.py         ← +6 targeted regimens appended (Issue 1)
├── pipeline_integration.py        ← +_prior_therapy_guard(), updated _build_safe_options(),
│                                      run_phase6(patient, journey_id, storage_backend) (Issues 2, 4)
├── clinical/policy_engine.py      ← +options_third_line field, 3L routing in get_options() (Issue 3)
├── clinical/cancers/
│   ├── breast/pathways.yaml       ← +third_line section (4 regimens) (Issue 3)
│   ├── colorectal/pathways.yaml   ← +third_line section (4 regimens) (Issue 3)
│   └── prostate/pathways.yaml     ← +third_line_CRPC section (4 regimens) (Issue 3)
├── patient_journey.py             ← NEW: PatientJourney, TreatmentEpisode, StorageBackend (Issue 4)
└── tests/test_phase10_fixes.py    ← NEW: 20 tests covering all 4 issues
```

## 🧪 Running Phase 10 Tests

```bash
cd engine
pytest tests/test_phase10_fixes.py -v

# Or run directly:
python tests/test_phase10_fixes.py
```

## 🔌 Using PatientJourney (Issue 4)

```python
from patient_journey import PatientJourney, TreatmentEpisode, JSONStorageBackend
from pipeline_integration import run_phase6

# Create or load a patient journey
backend = JSONStorageBackend("/data/journeys")
journey = PatientJourney("patient_001", {"age": 65, "sex": "F"}, backend)

# Add a treatment episode after a decision
episode = TreatmentEpisode(
    episode_num=1,
    regimen="Osimertinib 1L",
    start_date="2024-01-15",
    end_date="2024-11-20",
    outcome="PD",
    toxicity="mild",
)
journey.add_episode(episode)
journey.save()

# On next visit, pass journey_id — prior therapies auto-excluded
result = run_phase6(patient_dict, journey_id="patient_001", storage_backend=backend)
```
