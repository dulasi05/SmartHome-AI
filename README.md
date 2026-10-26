# Explainable Transformer-Based Multi-Resident Activity Recognition and Behavioural Anomaly Monitoring in IoT-Enabled Smart Homes

An end-to-end research-oriented prototype implementing multi-resident activity recognition and behavioral anomaly detection using ambient smart-home sensors (ARAS / CASAS datasets) and an explainable Powerformer architecture.

---

## Architecture Overview

```
Layer 1: Sensor Data Ingestion & Preprocessing
  - Public smart-home datasets (ARAS House A/B, CASAS)
  - Synthetic dataset generator for reproduction (synthetic_aras.csv)
  - Sliding-window temporal feature encoding with state & time-delta embeddings

Layer 2: Multi-Resident Activity Recognition
  - Powerformer-style Transformer with Weighted Causal Multi-Head Attention (WC-MHA)
  - Power-law temporal decay matrix: W_ij = (1 + |t_i - t_j| / scale)^(-alpha)
  - Multi-head output for concurrent multi-resident activity classification

Layer 3: Confidence Calibration
  - Temperature scaling post-processing: p_cal = softmax(logits / T)
  - Expected Calibration Error (ECE) minimization via validation NLL
  - Reliability diagrams with bin-level confidence vs empirical accuracy

Layer 4: Routine Profiling & Behavioural Anomaly Detection
  - Per-resident hourly activity probability baseline distributions
  - Jensen-Shannon Divergence (JSD) deviation scoring with interval estimation
  - Daily multi-factor feature extraction + Isolation Forest anomaly detection
  - Realistic anomaly injection engine (night activity, prolonged absence, frequency spike)

Layer 5: Decision Support & Explainability
  - Three-tier confidence-aware alert prioritisation (CONFIRMED, NEEDS_REVIEW, LOGGED_NORMAL)
  - MO-TLIME feature attribution (sensor contribution & temporal segment importance)
  - Interactive multi-page React dashboard with live simulator and dark glassmorphic design
```

---

## Project Structure

```
smarthome/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── dashboard.py         # Phase 1 dashboard KPIs & analytics
│   │   │   ├── datasets.py          # Dataset upload & management
│   │   │   ├── ml_routes.py         # Phase 2 training, calibration, anomaly & alert APIs
│   │   │   ├── predictions.py       # Live activity predictions
│   │   │   └── sensors.py           # Real-time sensor stream & simulator
│   │   ├── core/
│   │   │   ├── config.py            # Application configuration
│   │   │   └── database.py          # SQLite database connection & session
│   │   ├── ml/
│   │   │   ├── alert_prioritisation.py # Three-tier alert prioritisation engine
│   │   │   ├── anomaly_detection.py    # Isolation Forest & synthetic anomaly injector
│   │   │   ├── confidence_calibration.py # Temperature scaling & ECE metrics
│   │   │   ├── explainability.py       # MO-TLIME sensor & segment explainer
│   │   │   ├── powerformer.py          # WC-MHA Transformer architecture
│   │   │   ├── routine_profile.py      # Hourly baseline profiles & JSD deviation scorer
│   │   │   └── synthetic_dataset.py    # Reproducible 12k-row ARAS generator
│   │   ├── models/
│   │   │   └── db_models.py         # SQLAlchemy ORM models
│   │   ├── services/
│   │   │   ├── intelligence.py      # AI rule engine & activity taxonomy
│   │   │   ├── preprocessor.py      # Feature extraction & normalization
│   │   │   ├── simulator.py         # Sensor simulation engine
│   │   │   └── training_service.py  # Model training pipeline orchestration
│   │   └── main.py                  # FastAPI application entry point
│   ├── data/
│   │   └── raw/synthetic_aras.csv   # Pre-generated 12k-row synthetic ARAS dataset
│   └── tests/
│       └── test_phase2.py           # Complete test suite (50 tests, 100% pass)
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── MetricCard.jsx       # Reusable analytics card
    │   │   └── Sidebar.jsx          # Dual-phase navigation bar
    │   ├── pages/
    │   │   ├── OverviewDashboard.jsx    # System overview & live sensor summary
    │   │   ├── LiveSensorMonitoring.jsx # Real-time sensor states & simulator control
    │   │   ├── DatasetStudio.jsx        # Dataset upload & raw event browser
    │   │   ├── ModelTraining.jsx        # Phase 2: Powerformer training & ECE calibration
    │   │   ├── AlertCentre.jsx          # Phase 2: Tiered anomaly alerts & review actions
    │   │   └── Explainability.jsx       # Phase 2: MO-TLIME sensor & segment importance
    │   ├── App.jsx                  # React Router configuration
    │   ├── index.css                # Premium dark glassmorphism design system
    │   └── main.jsx
    └── vite.config.js               # Vite config with API proxy to port 8000
```

---

## Running the Application

### 1. Prerequisites
- Python 3.12+ (or Python 3.15) with PyTorch, FastAPI, and Scikit-learn
- Node.js 18+ and npm

### 2. Backend Server
```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- API Base URL: `http://127.0.0.1:8000`
- Interactive Swagger UI: `http://127.0.0.1:8000/api/docs`
- ReDoc Documentation: `http://127.0.0.1:8000/api/redoc`

### 3. Frontend Web Dashboard
```bash
cd frontend
npm run dev
```
- Web Application: `http://localhost:3000`

---

## Running Automated Tests

To run the complete test suite covering the entire Phase 2 machine learning pipeline:

```bash
cd backend
python -m pytest tests/test_phase2.py -v
```

All 50 unit and integration tests validate:
- Powerformer forward pass, causal masking, and power-law attention decay
- Expected Calibration Error (ECE) and temperature scaling
- Jensen-Shannon Divergence hourly routine deviation estimation
- Daily feature extraction and Isolation Forest anomaly scoring
- Synthetic anomaly injection (Night Activity, Time Shift)
- Three-tier alert prioritisation and ambiguity penalisation
- End-to-end FastAPI endpoints and database transactions
