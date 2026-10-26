/**
 * Explainability Page — Phase 2
 * MO-TLIME-style sensor and time-segment explanations.
 */
import { useState } from 'react';
import { BrainCircuit, Play, AlertTriangle, RefreshCw, Info } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import { explainPrediction } from '../services/api';
import { useToast } from '../hooks/useToast';

const DIR_COLORS = {
  positive: '#10b981',
  negative: '#ef4444',
  neutral: '#94a3b8',
};

export default function Explainability() {
  const { addToast } = useToast();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [residentId, setResidentId] = useState('R1');
  const [windowSize, setWindowSize] = useState(30);
  const [nPerturbations, setNPerturbations] = useState(100);

  const handleExplain = async () => {
    setLoading(true);
    try {
      const data = await explainPrediction(residentId, windowSize, nPerturbations);
      setResult(data);
      addToast('✅ Explanation generated', 'success');
    } catch (e) {
      addToast(`Failed: ${e.response?.data?.detail || e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const sensorChartData = result?.sensor_contributions?.slice(0, 8).map(sc => ({
    name: sc.sensor_id.replace('_', '\n'),
    fullName: sc.sensor_id,
    importance: sc.importance_score,
    direction: sc.direction,
  })) || [];

  const timeChartData = result?.time_contributions?.map(tc => ({
    name: tc.time_label,
    importance: tc.importance_score,
    direction: tc.direction,
    events: tc.events_in_segment,
  })) || [];

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Explainability</h2>
            <p>MO-TLIME-style local explanations for activity predictions</p>
          </div>
        </div>
      </div>

      <div className="page-body">
        {/* Method note */}
        <div className="demo-banner" style={{ marginBottom: 20 }}>
          <Info size={14} />
          <span>
            <strong>MO-TLIME-style:</strong> Local explanations via Ridge regression on binary sensor/time masks.
            Importance scores reflect actual model responses to perturbations — not hardcoded values.
            See module documentation for differences from the published MO-TLIME formulation.
          </span>
        </div>

        <div className="grid-2-1 mb-6">
          {/* Controls */}
          <div className="card">
            <div className="card-header">
              <div className="card-title"><BrainCircuit size={16} /> Generate Explanation</div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              <div>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Resident</label>
                <select
                  className="input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  value={residentId}
                  onChange={e => setResidentId(e.target.value)}
                >
                  <option value="R1">R1</option>
                  <option value="R2">R2</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Window Size</label>
                <input
                  type="number"
                  className="input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  value={windowSize}
                  min={5}
                  max={200}
                  onChange={e => setWindowSize(parseInt(e.target.value))}
                />
              </div>
              <div>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Perturbations</label>
                <input
                  type="number"
                  className="input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  value={nPerturbations}
                  min={30}
                  max={500}
                  onChange={e => setNPerturbations(parseInt(e.target.value))}
                />
              </div>
            </div>

            <button
              className="btn btn-primary"
              style={{ width: '100%' }}
              onClick={handleExplain}
              disabled={loading}
            >
              {loading
                ? <><div className="spinner" style={{ width: 14, height: 14 }} /> Explaining…</>
                : <><Play size={14} /> Generate Explanation</>
              }
            </button>

            {result && (
              <div style={{ marginTop: 16 }}>
                <div style={{
                  background: 'var(--primary-glow)', borderRadius: 10, padding: 14,
                  border: '1px solid rgba(91,141,238,0.2)',
                }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--primary-light)', marginBottom: 6 }}>
                    Predicted: <span style={{ textTransform: 'capitalize' }}>
                      {result.predicted_activity?.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>
                    Confidence: {(result.predicted_prob * 100)?.toFixed(1)}%
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>
                    Surrogate R²: {result.surrogate_r2?.toFixed(3)}
                    {result.surrogate_r2 < 0.3 && (
                      <span style={{ color: 'var(--warning)', marginLeft: 6 }}>⚠️ Low fidelity</span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    Mode: {result.mode} · {result.perturbed_samples} perturbations
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Plain English */}
          {result && (
            <div className="card">
              <div className="card-header">
                <div className="card-title"><Info size={16} /> Plain English Explanation</div>
              </div>
              <div style={{
                fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.8,
                padding: 12, background: 'var(--bg-card)', borderRadius: 8,
                border: '1px solid var(--border)',
              }}>
                {result.plain_english}
              </div>
              {result.method_note && (
                <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                  {result.method_note}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Sensor importance chart */}
        {sensorChartData.length > 0 && (
          <div className="card mb-6">
            <div className="card-header">
              <div className="card-title">Sensor Importance Scores</div>
              <span className="badge badge-info">{sensorChartData.length} sensors</span>
            </div>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={sensorChartData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis type="number" domain={[0, 1]} stroke="var(--text-muted)" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="name" stroke="var(--text-muted)" tick={{ fontSize: 10 }} width={100} />
                <Tooltip
                  contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }}
                  formatter={(v, n, props) => [v.toFixed(4), `${props.payload.fullName} (${props.payload.direction})`]}
                />
                <Bar dataKey="importance" radius={[0, 4, 4, 0]}>
                  {sensorChartData.map((entry, i) => (
                    <Cell key={i} fill={DIR_COLORS[entry.direction] || '#94a3b8'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11 }}>
              <span style={{ color: DIR_COLORS.positive }}>■ Positive (increases prediction)</span>
              <span style={{ color: DIR_COLORS.negative }}>■ Negative (decreases prediction)</span>
              <span style={{ color: DIR_COLORS.neutral }}>■ Neutral</span>
            </div>
          </div>
        )}

        {/* Time segment importance */}
        {timeChartData.length > 0 && (
          <div className="card mb-6">
            <div className="card-header">
              <div className="card-title">Time Segment Importance</div>
            </div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={timeChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" stroke="var(--text-muted)" tick={{ fontSize: 10 }} />
                <YAxis stroke="var(--text-muted)" tick={{ fontSize: 10 }} domain={[0, 'auto']} />
                <Tooltip
                  contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }}
                  formatter={(v, name) => [v.toFixed(4), name]}
                />
                <Bar dataKey="importance" radius={4}>
                  {timeChartData.map((entry, i) => (
                    <Cell key={i} fill={DIR_COLORS[entry.direction] || '#94a3b8'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Sensor detail table */}
        {result?.sensor_contributions?.length > 0 && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Sensor Contribution Details</div>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Sensor', 'Importance', 'Direction', 'Events', 'Explanation'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.sensor_contributions.map((sc, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '8px 12px', fontWeight: 600 }}>{sc.sensor_id}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{
                            width: `${Math.round(sc.importance_score * 80)}px`,
                            height: 6, borderRadius: 3,
                            background: DIR_COLORS[sc.direction],
                          }} />
                          {sc.importance_score.toFixed(4)}
                        </div>
                      </td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{ color: DIR_COLORS[sc.direction], fontSize: 11, fontWeight: 600, textTransform: 'capitalize' }}>
                          {sc.direction}
                        </span>
                      </td>
                      <td style={{ padding: '8px 12px' }}>{sc.event_count}</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)', maxWidth: 300 }}>
                        {sc.explanation_text}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
