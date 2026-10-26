/**
 * System Architecture Page
 * Visualizes all 5 layers with technology, responsibilities, data flow arrows, and status.
 */
import { useState, useEffect } from 'react';
import {
  Database, Cpu, Layers, Server, Monitor,
  ArrowDown, RefreshCw, CheckCircle, AlertCircle, Info
} from 'lucide-react';
import { getPipelineStatus } from '../services/api';
import { useToast } from '../hooks/useToast';

const LAYER_CONFIG = [
  {
    id: 1,
    name: 'Data Layer',
    icon: Database,
    color: '#5b8dee',
    gradient: 'linear-gradient(135deg, #5b8dee 0%, #3b6fd4 100%)',
    technology: 'ARAS/CASAS Datasets · CSV Upload · Sensor Simulator · MQTT (future)',
    responsibilities: [
      'Import CSV datasets (ARAS, CASAS, custom)',
      'Sensor event ingestion via REST API',
      'Simulated sensor events (timestamped, realistic)',
      'Distinguish dataset vs. simulator sources',
      'Extensible adapter for physical sensors (PIR, door, etc.)',
      'Live event table with latest readings',
    ],
    futureNote: 'MQTT/HTTP gateway integration planned for physical hardware.',
  },
  {
    id: 2,
    name: 'Processing Layer',
    icon: Cpu,
    color: '#06b6d4',
    gradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
    technology: 'Python · Pandas · scikit-learn',
    responsibilities: [
      'Data cleaning and deduplication',
      'Timestamp normalization',
      'Missing value and invalid record handling',
      'Sensor event encoding (categorical → numerical)',
      'Configurable sliding window generation (default: 30 events, step 10)',
      'Feature extraction (temporal, activation counts, on/off ratios)',
      'Time-ordered train/validation/test splitting (no data leakage)',
    ],
    futureNote: 'Window size and step configurable per model requirement.',
  },
  {
    id: 3,
    name: 'Intelligence Layer',
    icon: Layers,
    color: '#a855f7',
    gradient: 'linear-gradient(135deg, #a855f7 0%, #7c3aed 100%)',
    technology: 'Powerformer/WC-MHA [DEMO] · MO-TLIME Explainer [DEMO]',
    responsibilities: [
      '⚠️ DEMO: Heuristic predictions (real model not yet integrated)',
      'Activity recognition: sleeping, cooking, walking, leaving, etc.',
      'Confidence scoring per prediction',
      'MO-TLIME style feature importance (demo approximation)',
      'Anomaly scoring via statistical deviation from recent history',
      'Resident routine profile generation and maintenance',
      'Modular interface — swap in real Powerformer/WC-MHA when ready',
    ],
    futureNote: 'Replace _predict_with_model() in intelligence.py to integrate the real model.',
    isDemoLayer: true,
  },
  {
    id: 4,
    name: 'Storage Layer',
    icon: Server,
    color: '#10b981',
    gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    technology: 'SQLite · SQLAlchemy ORM',
    responsibilities: [
      'Sensor events table (timestamps, states, resident IDs, source)',
      'Activity predictions table (activity, confidence, anomaly score)',
      'Prediction explanations table (sensor importance, direction)',
      'Anomaly alerts table (severity, reason, affected sensors, status)',
      'Resident routine profiles (JSON activity sequences)',
      'Dataset upload records (filename, stats, status)',
      'Sensor metadata registry',
      'Duplicate prevention across re-processing runs',
    ],
    futureNote: 'Can be migrated to PostgreSQL for production deployment.',
  },
  {
    id: 5,
    name: 'Presentation Layer',
    icon: Monitor,
    color: '#f59e0b',
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    technology: 'React · Vite · Recharts · FastAPI · REST API',
    responsibilities: [
      'Overview dashboard with live stats and current activity',
      'Live sensor event stream with source labels',
      'Activity recognition with explanation bars',
      'Routine analysis with hourly charts',
      'Anomaly alerts with status management',
      'Dataset upload and preview',
      'System architecture visualization (this page)',
      'All data retrieved from SQLite — no hardcoded cards',
      'Responsive design (desktop, tablet, mobile)',
    ],
    futureNote: 'Add WebSocket for true real-time streaming.',
  },
];

export default function SystemArchitecture() {
  const { addToast } = useToast();
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    try {
      const data = await getPipelineStatus();
      setPipelineStatus(data);
    } catch {
      addToast('Failed to load pipeline status', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatus(); }, []);

  const getLayerStatus = (layerId) => {
    return pipelineStatus?.layers?.find(l => l.id === layerId);
  };

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>System Architecture</h2>
            <p>5-layer smart home activity recognition pipeline — exact data flow from sensor to dashboard</p>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={fetchStatus}>
            <RefreshCw size={14} /> Refresh Status
          </button>
        </div>
      </div>

      <div className="page-body">
        {/* Data flow header */}
        <div style={{
          background: 'linear-gradient(135deg, var(--bg-card) 0%, var(--bg-surface) 100%)',
          border: '1px solid var(--border)',
          borderRadius: 16, padding: '16px 24px', marginBottom: 24,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>Data Flow</div>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexWrap: 'wrap', gap: 8, fontSize: 13, fontWeight: 600,
          }}>
            {['Data', 'Processing', 'Intelligence', 'Storage', 'Presentation'].map((l, i, arr) => (
              <span key={l} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  padding: '4px 14px', borderRadius: 20,
                  background: LAYER_CONFIG[i].gradient,
                  color: 'white', fontSize: 12,
                }}>{l}</span>
                {i < arr.length - 1 && <span style={{ color: 'var(--text-muted)', fontSize: 16 }}>→</span>}
              </span>
            ))}
          </div>
        </div>

        {/* Layer cards */}
        <div className="pipeline-container">
          {LAYER_CONFIG.map((layer, idx) => {
            const status = getLayerStatus(layer.id);
            const Icon = layer.icon;
            return (
              <div key={layer.id}>
                <div className="pipeline-layer" style={{
                  borderLeft: `4px solid ${layer.color}`,
                }}>
                  <div className="pipeline-layer-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1 }}>
                      <div style={{
                        width: 44, height: 44, borderRadius: 12,
                        background: layer.gradient,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        boxShadow: `0 4px 16px ${layer.color}40`,
                        flexShrink: 0,
                      }}>
                        <Icon size={22} color="white" />
                      </div>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{
                            width: 24, height: 24, background: layer.gradient,
                            borderRadius: 6, display: 'flex', alignItems: 'center',
                            justifyContent: 'center', fontSize: 12, fontWeight: 800, color: 'white',
                          }}>
                            {layer.id}
                          </div>
                          <span className="pipeline-layer-title">{layer.name}</span>
                          {layer.isDemoLayer && (
                            <span className="badge badge-demo">⚠️ DEMO</span>
                          )}
                        </div>
                        <div style={{ marginTop: 2 }}>
                          <span className="pipeline-tech">{layer.technology}</span>
                        </div>
                      </div>
                    </div>

                    {/* Status badge */}
                    {status && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {status.event_count != null && (
                          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                            {status.event_count} events
                          </span>
                        )}
                        {status.prediction_count != null && (
                          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                            {status.prediction_count} predictions
                          </span>
                        )}
                        <span className={`badge ${
                          status.status === 'connected' ? 'badge-success' :
                          status.status === 'demo' ? 'badge-demo' :
                          status.status === 'running' ? 'badge-info' :
                          status.status === 'ready' ? 'badge-success' :
                          status.status === 'idle' ? 'badge-neutral' : 'badge-error'
                        }`}>
                          {loading ? '…' : status.status_label}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Responsibilities */}
                  <div style={{ paddingLeft: 56 }}>
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        Responsibilities
                      </div>
                      <div className="pipeline-responsibilities">
                        {layer.responsibilities.map((r, i) => (
                          <span key={i} className={`pipeline-tag${r.startsWith('⚠️') ? ' badge-demo' : ''}`}>
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Future note */}
                    {layer.futureNote && (
                      <div style={{
                        display: 'flex', alignItems: 'flex-start', gap: 6,
                        fontSize: 11, color: 'var(--text-muted)',
                        background: 'var(--bg-surface)', borderRadius: 6,
                        padding: '6px 10px', border: '1px solid var(--border)',
                        maxWidth: 600,
                      }}>
                        <Info size={12} style={{ flexShrink: 0, marginTop: 1 }} />
                        <span>{layer.futureNote}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Arrow between layers */}
                {idx < LAYER_CONFIG.length - 1 && (
                  <div className="pipeline-arrow">
                    <ArrowDown size={18} color={layer.color} style={{ position: 'relative', zIndex: 1 }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Hardware adapter note */}
        <div style={{
          marginTop: 24, padding: 20,
          background: 'linear-gradient(135deg, rgba(91,141,238,0.08) 0%, rgba(168,85,247,0.05) 100%)',
          border: '1px solid rgba(91,141,238,0.2)',
          borderRadius: 16,
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
            🔌 Hardware Integration Roadmap
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            <strong>Current state:</strong> The system works without physical hardware using uploaded datasets and a sensor simulator.<br />
            <strong>MQTT integration:</strong> A sensor gateway (e.g., Mosquitto broker) can publish events to <code>/sensors/events</code> REST endpoint.<br />
            <strong>PIR/Door sensors:</strong> Map hardware readings to the standard SensorEvent schema (sensor_id, sensor_state, timestamp).<br />
            <strong>Extensibility:</strong> The Data Layer's ingestion interface is modular — add a new adapter without changing Processing or Intelligence layers.
          </div>
        </div>
      </div>
    </div>
  );
}
