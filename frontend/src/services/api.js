/**
 * API service layer for the Smart Home Activity Recognition System.
 * All backend calls go through this module.
 */

import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
});

// ── Health ────────────────────────────────────────────────────────────────────
export const checkHealth = () => api.get('/health').then(r => r.data);

// ── Dashboard ─────────────────────────────────────────────────────────────────
export const getDashboardStats = (hours = 24) =>
  api.get('/dashboard/stats', { params: { hours } }).then(r => r.data);

export const getPipelineStatus = () =>
  api.get('/dashboard/pipeline-status').then(r => r.data);

export const getActivityHistory = (residentId = 'R1', hours = 24) =>
  api.get('/dashboard/activity-history', { params: { resident_id: residentId, hours } }).then(r => r.data);

// ── Sensor events ─────────────────────────────────────────────────────────────
export const getSensorEvents = (params = {}) =>
  api.get('/sensors/events', { params }).then(r => r.data);

export const simulateSensorEvents = (count = 10, residentId = 'R1') =>
  api.post('/sensors/simulate', null, { params: { count, resident_id: residentId } }).then(r => r.data);

export const generateHistoricalData = (days = 3, residentId = 'R1') =>
  api.post('/sensors/simulate/historical', null, { params: { days, resident_id: residentId } }).then(r => r.data);

export const getSensorMetadata = () =>
  api.get('/sensors/metadata').then(r => r.data);

// ── Predictions ───────────────────────────────────────────────────────────────
export const runPrediction = (residentId = 'R1', windowSize = 30) =>
  api.post('/predictions/run', { resident_id: residentId, window_size: windowSize }).then(r => r.data);

export const getPredictions = (params = {}) =>
  api.get('/predictions/', { params }).then(r => r.data);

export const getPredictionDetail = (id) =>
  api.get(`/predictions/${id}`).then(r => r.data);

export const getAnomalyAlerts = (params = {}) =>
  api.get('/predictions/anomalies/', { params }).then(r => r.data);

export const updateAlertStatus = (alertId, status) =>
  api.patch(`/predictions/anomalies/${alertId}/status`, null, { params: { status } }).then(r => r.data);

export const getRoutineProfile = (residentId) =>
  api.get(`/predictions/routines/${residentId}`).then(r => r.data);

// ── Datasets ──────────────────────────────────────────────────────────────────
export const uploadDataset = (file, datasetType = 'auto') => {
  const form = new FormData();
  form.append('file', file);
  form.append('dataset_type', datasetType);
  return api.post('/datasets/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data);
};

export const listDatasetUploads = () =>
  api.get('/datasets/').then(r => r.data);

export const getDatasetPreview = (uploadId, limit = 50) =>
  api.get(`/datasets/${uploadId}/preview`, { params: { limit } }).then(r => r.data);

// ── Phase 2 ML ───────────────────────────────────────────────────────────────

// Training
export const startTraining = (config = {}) =>
  api.post('/ml/train', config).then(r => r.data);

export const getTrainingStatus = () =>
  api.get('/ml/train/status').then(r => r.data);

// Phase-2 inference
export const runPhase2Prediction = (residentId = 'R1', windowSize = 30) =>
  api.post('/ml/predict', null, { params: { resident_id: residentId, window_size: windowSize } }).then(r => r.data);

// Explainability
export const explainPrediction = (residentId = 'R1', windowSize = 30, nPerturbations = 100) =>
  api.post('/ml/explain', null, {
    params: { resident_id: residentId, window_size: windowSize, n_perturbations: nPerturbations }
  }).then(r => r.data);

// Calibration
export const getCalibrationStatus = () =>
  api.get('/ml/calibration/status').then(r => r.data);

export const getCalibrationMetrics = () =>
  api.get('/ml/evaluation/calibration').then(r => r.data);

// Routine profiles
export const getRoutineSummary = () =>
  api.get('/ml/routines/summary').then(r => r.data);

export const getPhase2RoutineProfile = (residentId) =>
  api.get(`/ml/routines/${residentId}`).then(r => r.data);

export const scoreRoutineDeviation = (residentId, dateStr = null) =>
  api.post(`/ml/routines/${residentId}/score`, null, {
    params: dateStr ? { date_str: dateStr } : {}
  }).then(r => r.data);

// Anomaly injection
export const injectAnomaly = (params = {}) =>
  api.post('/ml/anomaly/inject', params).then(r => r.data);

// Phase-2 alerts
export const getPhase2Alerts = (params = {}) =>
  api.get('/ml/alerts/', { params }).then(r => r.data);

export const prioritiseAlert = (params = {}) =>
  api.post('/ml/alerts/prioritise', params).then(r => r.data);

export const reviewAlert = (alertId, reviewStatus, reviewNote = '', reviewedBy = 'caregiver') =>
  api.patch(`/ml/alerts/${alertId}/review`, null, {
    params: { review_status: reviewStatus, review_note: reviewNote, reviewed_by: reviewedBy }
  }).then(r => r.data);

// Evaluation
export const getEvaluationSummary = () =>
  api.get('/ml/evaluation/summary').then(r => r.data);

export default api;

