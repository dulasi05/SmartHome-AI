/**
 * Activity Recognition Page
 * Shows predictions, confidence, and MO-TLIME style explanations.
 */
import { useState, useEffect } from 'react';
import { Activity, Play, RefreshCw, Cpu, Info } from 'lucide-react';
import { getPredictions, runPrediction, getPredictionDetail, simulateSensorEvents } from '../services/api';
import { useToast } from '../hooks/useToast';

const ACTIVITY_COLORS = {
  sleeping: '#7c3aed', meal_preparation: '#f97316', eating: '#ef4444',
  washing_dishes: '#06b6d4', watching_tv: '#8b5cf6', working_at_computer: '#3b82f6',
  personal_hygiene: '#14b8a6', leaving_home: '#f59e0b', walking: '#10b981',
  reading: '#6366f1', resting: '#64748b', other: '#94a3b8',
};

const ACTIVITY_EMOJIS = {
  sleeping: '😴', meal_preparation: '🍳', eating: '🍽️',
  washing_dishes: '🧹', watching_tv: '📺', working_at_computer: '💻',
  personal_hygiene: '🚿', leaving_home: '🚪', walking: '🚶',
  reading: '📖', resting: '🛋️', other: '🏠',
};

function ExplanationBar({ exp }) {
  return (
    <div className="explanation-bar-row">
      <div className="explanation-bar-label">
        <span className="explanation-bar-sensor">{exp.sensor_id}</span>
        <span className="explanation-bar-score" style={{
          color: exp.direction === 'positive' ? 'var(--success)' : 'var(--error)'
        }}>
          {(exp.importance_score * 100).toFixed(0)}%
        </span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 5 }}>
        {exp.feature_name}
      </div>
      <div className="explanation-bar-bg">
        <div
          className={`explanation-bar-fill ${exp.direction}`}
          style={{ width: `${exp.importance_score * 100}%` }}
        />
      </div>
    </div>
  );
}

export default function ActivityRecognition() {
  const { addToast } = useToast();
  const [predictions, setPredictions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [residentId, setResidentId] = useState(
    () => localStorage.getItem('smartHome_residentId') || 'R1'
  );

  const fetchPredictions = async () => {
    try {
      const data = await getPredictions({ limit: 50, resident_id: residentId });
      setPredictions(data.predictions || []);
    } catch { addToast('Failed to load predictions', 'error'); }
    finally { setLoading(false); }
  };

  const fetchDetail = async (id) => {
    try {
      const d = await getPredictionDetail(id);
      setDetail(d);
    } catch { addToast('Failed to load prediction detail', 'error'); }
  };

  useEffect(() => {
    fetchPredictions();
  }, [residentId]);

  useEffect(() => {
    if (selectedId) fetchDetail(selectedId);
  }, [selectedId]);

  const handleRunPrediction = async () => {
    setRunning(true);
    try {
      await simulateSensorEvents(20, residentId);
      const result = await runPrediction(residentId, 30);
      addToast(`✅ Predicted: ${result.predicted_activity} (${(result.confidence * 100).toFixed(1)}%)`, 'success');
      await fetchPredictions();
      setSelectedId(result.prediction_id);
    } catch (err) {
      addToast(`Error: ${err.response?.data?.detail || err.message}`, 'error');
    } finally {
      setRunning(false);
    }
  };

  const latestPred = detail || (predictions.length > 0 ? null : null);
  const displayPred = detail;

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Activity History & Recognition</h2>
            <p>Chronological record of recognized household activities, detection confidence, and sensor contributions</p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <select
              value={residentId}
              onChange={e => {
                setResidentId(e.target.value);
                localStorage.setItem('smartHome_residentId', e.target.value);
              }}
              style={{ fontSize: 13 }}
            >
              <option value="R1">Resident 1 (Primary)</option>
              <option value="R2">Resident 2 (Guest)</option>
            </select>
            <button className="btn btn-secondary btn-sm" onClick={fetchPredictions}>
              <RefreshCw size={14} /> Refresh
            </button>
            <button className="btn btn-primary btn-sm" onClick={handleRunPrediction} disabled={running}>
              {running ? <div className="spinner" style={{ width: 14, height: 14 }} /> : <Play size={14} />}
              Analyze Current Activity
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        <div className="demo-banner">
          <Cpu size={16} />
          <strong>AI Status Note:</strong> Activity recognition is active using baseline rule inference. AI model training and checkpoint weights can be configured in Developer Tools.
        </div>

        <div className="grid-1-2">
          {/* Prediction detail panel */}
          <div>
            {displayPred ? (
              <div className="card mb-4">
                <div className="card-header">
                  <div className="card-title"><Activity size={16} /> Prediction #{displayPred.id}</div>
                  <span className={`badge ${displayPred.is_demo ? 'badge-demo' : 'badge-success'}`}>
                    {displayPred.is_demo ? '⚠️ DEMO' : '✅ REAL'}
                  </span>
                </div>

                {/* Activity */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: 16, background: 'var(--bg-surface)', borderRadius: 12,
                  marginBottom: 16,
                  border: `1px solid ${ACTIVITY_COLORS[displayPred.predicted_activity] || '#5b8dee'}30`,
                }}>
                  <div style={{ fontSize: 40 }}>
                    {ACTIVITY_EMOJIS[displayPred.predicted_activity] || '🏠'}
                  </div>
                  <div>
                    <div style={{
                      fontSize: 20, fontWeight: 800, textTransform: 'capitalize',
                      color: ACTIVITY_COLORS[displayPred.predicted_activity] || 'var(--primary-light)',
                    }}>
                      {displayPred.predicted_activity?.replace(/_/g, ' ')}
                    </div>
                    <div className="text-muted text-sm">
                      {new Date(displayPred.timestamp).toLocaleString()}
                    </div>
                  </div>
                </div>

                {/* Confidence */}
                <div className="mb-4">
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span className="text-sm text-secondary">Confidence Score</span>
                    <span className="confidence-number">{(displayPred.confidence * 100).toFixed(1)}%</span>
                  </div>
                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{
                        width: `${displayPred.confidence * 100}%`,
                        background: `linear-gradient(90deg, ${ACTIVITY_COLORS[displayPred.predicted_activity] || 'var(--primary)'}, var(--accent-cyan))`,
                      }}
                    />
                  </div>
                </div>

                {/* Anomaly */}
                {displayPred.anomaly_score !== null && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span className="text-sm text-secondary">Anomaly Score</span>
                      <span style={{
                        fontSize: 14, fontWeight: 700,
                        color: displayPred.is_anomaly ? 'var(--error)' : 'var(--success)',
                      }}>
                        {(displayPred.anomaly_score * 100).toFixed(0)}%
                        {displayPred.is_anomaly && ' ⚠️'}
                      </span>
                    </div>
                    <div className="progress-bar">
                      <div
                        className="progress-fill"
                        style={{
                          width: `${displayPred.anomaly_score * 100}%`,
                          background: displayPred.is_anomaly
                            ? 'linear-gradient(90deg, var(--error), var(--accent-amber))'
                            : 'linear-gradient(90deg, var(--success), var(--accent-cyan))',
                        }}
                      />
                    </div>
                  </div>
                )}

                {/* Meta */}
                <div style={{ fontSize: 11, color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                  <div>Model: <code>{displayPred.model_name}</code></div>
                  {displayPred.window_start && (
                    <div>Window: {new Date(displayPred.window_start).toLocaleTimeString()} → {new Date(displayPred.window_end).toLocaleTimeString()}</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="card mb-4">
                <div className="empty-state">
                  <Activity size={32} />
                  <p>Select a prediction or run a new one</p>
                </div>
              </div>
            )}

            {/* Explanations */}
            {displayPred?.explanations?.length > 0 && (
              <div className="card">
                <div className="card-header">
                  <div className="card-title">
                    <Info size={16} /> Influential Sensors
                  </div>
                  <span className="badge badge-demo">MO-TLIME [DEMO]</span>
                </div>
                {displayPred.explanations.map((exp, i) => (
                  <ExplanationBar key={i} exp={exp} />
                ))}
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
                  ⚠️ These explanations are heuristic approximations, not real MO-TLIME outputs.
                </div>
              </div>
            )}
          </div>

          {/* Prediction history */}
          <div>
            <div className="card">
              <div className="card-header">
                <div className="card-title">Prediction History</div>
                <span className="badge badge-neutral">{predictions.length}</span>
              </div>
              {loading ? (
                <div style={{ textAlign: 'center', padding: 24 }}>
                  <div className="spinner" style={{ margin: '0 auto' }} />
                </div>
              ) : predictions.length === 0 ? (
                <div className="empty-state">
                  <Activity size={28} />
                  <p>No predictions yet</p>
                </div>
              ) : (
                <div style={{ maxHeight: 520, overflowY: 'auto' }}>
                  {predictions.map(p => (
                    <div
                      key={p.id}
                      onClick={() => setSelectedId(p.id)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 8px',
                        borderRadius: 8, cursor: 'pointer', marginBottom: 4,
                        background: selectedId === p.id ? 'var(--primary-glow)' : 'transparent',
                        border: selectedId === p.id ? '1px solid rgba(91,141,238,0.3)' : '1px solid transparent',
                        transition: 'all 0.15s ease',
                      }}
                    >
                      <span style={{ fontSize: 20 }}>
                        {ACTIVITY_EMOJIS[p.predicted_activity] || '🏠'}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, textTransform: 'capitalize',
                          color: ACTIVITY_COLORS[p.predicted_activity] || 'var(--text-primary)',
                        }}>
                          {p.predicted_activity?.replace(/_/g, ' ')}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {new Date(p.timestamp).toLocaleString()}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-cyan)' }}>
                          {(p.confidence * 100).toFixed(0)}%
                        </div>
                        {p.is_anomaly && <span style={{ fontSize: 10, color: 'var(--error)' }}>⚠️ anomaly</span>}
                      </div>
                      <span className={`badge ${p.is_demo ? 'badge-demo' : 'badge-success'}`}>
                        {p.is_demo ? 'D' : 'R'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
