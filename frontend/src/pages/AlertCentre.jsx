/**
 * Alert Centre Page — Phase 2
 * Three-tier confidence-aware alert prioritisation dashboard.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  AlertTriangle, CheckCircle2, Clock, Eye, RefreshCw,
  ShieldAlert, ShieldCheck, Shield, Play, Zap
} from 'lucide-react';
import {
  getPhase2Alerts, prioritiseAlert, reviewAlert, injectAnomaly
} from '../services/api';
import { useToast } from '../hooks/useToast';

const TIER_CONFIG = {
  CONFIRMED: {
    label: 'Confirmed Alert',
    color: 'var(--error)',
    bg: 'rgba(239,68,68,0.08)',
    border: 'rgba(239,68,68,0.3)',
    icon: <ShieldAlert size={16} />,
    badgeClass: 'badge-error',
  },
  NEEDS_REVIEW: {
    label: 'Needs Review',
    color: 'var(--warning)',
    bg: 'rgba(245,158,11,0.08)',
    border: 'rgba(245,158,11,0.3)',
    icon: <Eye size={16} />,
    badgeClass: 'badge-warning',
  },
  LOGGED_NORMAL: {
    label: 'Logged Normal',
    color: 'var(--success)',
    bg: 'rgba(16,185,129,0.05)',
    border: 'rgba(16,185,129,0.15)',
    icon: <ShieldCheck size={16} />,
    badgeClass: 'badge-success',
  },
};

function AlertCard({ alert, onReview }) {
  const tier = TIER_CONFIG[alert.tier] || TIER_CONFIG.LOGGED_NORMAL;
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{
      background: tier.bg,
      border: `1px solid ${tier.border}`,
      borderRadius: 12,
      padding: 16,
      marginBottom: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ color: tier.color, flexShrink: 0, marginTop: 2 }}>
          {tier.icon}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap' }}>
            <div>
              <span className={`badge ${tier.badgeClass}`} style={{ marginRight: 8 }}>{tier.label}</span>
              <span className="badge badge-neutral">Resident: {alert.resident_id}</span>
              {alert.is_synthetic && <span className="badge badge-demo" style={{ marginLeft: 4 }}>SYNTHETIC</span>}
              {alert.insufficient_evidence && <span className="badge badge-neutral" style={{ marginLeft: 4 }}>⚠️ Low Evidence</span>}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {alert.review_status !== 'pending' && (
                <span style={{ fontSize: 11, color: 'var(--success)' }}>✓ {alert.review_status}</span>
              )}
              <button
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 11, padding: '3px 10px' }}
                onClick={() => setExpanded(e => !e)}
              >
                {expanded ? 'Less' : 'Details'}
              </button>
              {alert.tier !== 'LOGGED_NORMAL' && alert.review_status === 'pending' && (
                <button
                  className="btn btn-primary btn-sm"
                  style={{ fontSize: 11, padding: '3px 10px' }}
                  onClick={() => onReview(alert.alert_id)}
                >
                  Review
                </button>
              )}
            </div>
          </div>

          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {alert.plain_english}
          </div>

          <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap' }}>
            {[
              { label: 'Deviation', value: alert.deviation_score?.toFixed(3) },
              { label: 'Interval', value: `[${alert.deviation_low?.toFixed(2)}, ${alert.deviation_high?.toFixed(2)}]` },
              { label: 'Confidence', value: `${(alert.mean_calibrated_confidence * 100).toFixed(1)}%` },
              { label: 'Ambiguity', value: `${(alert.ambiguity_score * 100).toFixed(1)}%` },
              { label: 'Evidence', value: alert.evidence_score?.toFixed(3) },
              { label: 'Priority', value: alert.priority_score?.toFixed(3) },
            ].map(({ label, value }) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: tier.color }}>{value}</div>
              </div>
            ))}
          </div>

          {expanded && (
            <div style={{ marginTop: 12, padding: 12, background: 'var(--bg-card)', borderRadius: 8, fontSize: 11 }}>
              <div style={{ marginBottom: 6 }}>
                <strong>Date:</strong> {alert.date} &nbsp;
                <strong>Sensors:</strong> {alert.top_sensors?.join(', ') || 'N/A'}
              </div>
              <div style={{ marginBottom: 6 }}>
                <strong>Created:</strong> {new Date(alert.created_at).toLocaleString()}
              </div>
              <div style={{
                padding: 10, background: 'rgba(245,158,11,0.06)', borderRadius: 6,
                borderLeft: '3px solid var(--warning)', marginTop: 8,
                color: 'var(--text-muted)', lineHeight: 1.5,
              }}>
                {alert.disclaimer}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AlertCentre() {
  const { addToast } = useToast();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterTier, setFilterTier] = useState('');
  const [filterResident, setFilterResident] = useState('');
  const [injecting, setInjecting] = useState(false);
  const [injectType, setInjectType] = useState('NIGHT_ACTIVITY');
  const [injectSeverity, setInjectSeverity] = useState('medium');
  const [prioritising, setPrioritising] = useState(false);
  const [prioResident, setPrioResident] = useState('R1');

  const fetchAlerts = useCallback(async () => {
    try {
      const params = {};
      if (filterTier) params.tier = filterTier;
      if (filterResident) params.resident_id = filterResident;
      const data = await getPhase2Alerts(params);
      setAlerts(data.alerts || []);
    } catch (e) {
      addToast('Failed to load alerts', 'error');
    } finally {
      setLoading(false);
    }
  }, [filterTier, filterResident, addToast]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  const handleReview = async (alertId) => {
    try {
      await reviewAlert(alertId, 'reviewed', 'Reviewed via dashboard', 'caregiver');
      addToast('✅ Alert marked as reviewed', 'success');
      fetchAlerts();
    } catch (e) {
      addToast('Failed to update review', 'error');
    }
  };

  const handleInject = async () => {
    setInjecting(true);
    try {
      const result = await injectAnomaly({
        anomaly_type: injectType,
        severity: injectSeverity,
        resident_id: 'R1',
        seed: Math.floor(Math.random() * 1000),
      });
      addToast(`✅ Injected ${result.anomaly_type} (ID: ${result.injection_id})`, 'success');
    } catch (e) {
      addToast(`Injection failed: ${e.response?.data?.detail || e.message}`, 'error');
    } finally {
      setInjecting(false);
    }
  };

  const handlePrioritise = async () => {
    setPrioritising(true);
    try {
      const result = await prioritiseAlert({
        resident_id: prioResident,
        tau: 0.25,
        tau_E: 0.40,
      });
      addToast(`Alert created: Tier=${result.tier}, Priority=${result.priority_score?.toFixed(3)}`, 'info');
      fetchAlerts();
    } catch (e) {
      addToast(`Prioritisation failed: ${e.response?.data?.detail || e.message}`, 'error');
    } finally {
      setPrioritising(false);
    }
  };

  const tierCounts = { CONFIRMED: 0, NEEDS_REVIEW: 0, LOGGED_NORMAL: 0 };
  alerts.forEach(a => { if (tierCounts[a.tier] !== undefined) tierCounts[a.tier]++; });

  const filteredAlerts = [...alerts].reverse();

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Alert Centre</h2>
            <p>Confidence-aware three-tier anomaly alert prioritisation</p>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={fetchAlerts}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <div className="page-body">
        {/* Disclaimer */}
        <div className="demo-banner" style={{ background: 'rgba(245,158,11,0.06)', borderColor: 'var(--warning)', marginBottom: 20 }}>
          <ShieldAlert size={16} />
          <span>
            <strong>Important:</strong> Alerts indicate statistical deviations from routine.
            They are <strong>NOT</strong> medical diagnoses or emergency determinations.
            Human review is always required before taking any action.
          </span>
        </div>

        {/* Tier Summary */}
        <div className="stats-grid mb-6">
          {Object.entries(TIER_CONFIG).map(([tier, cfg]) => (
            <div
              key={tier}
              className="stat-card"
              style={{ cursor: 'pointer', border: filterTier === tier ? `2px solid ${cfg.color}` : undefined }}
              onClick={() => setFilterTier(t => t === tier ? '' : tier)}
            >
              <div className="stat-icon" style={{ background: cfg.bg }}>
                <span style={{ color: cfg.color }}>{cfg.icon}</span>
              </div>
              <div className="stat-value" style={{ color: cfg.color }}>{tierCounts[tier]}</div>
              <div className="stat-label">{cfg.label}</div>
            </div>
          ))}
        </div>

        <div className="grid-2-1 mb-6">
          {/* Alerts list */}
          <div>
            {/* Filters */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <select
                className="input"
                style={{ padding: '6px 12px', fontSize: 12, width: 'auto' }}
                value={filterTier}
                onChange={e => setFilterTier(e.target.value)}
              >
                <option value="">All Tiers</option>
                <option value="CONFIRMED">Confirmed</option>
                <option value="NEEDS_REVIEW">Needs Review</option>
                <option value="LOGGED_NORMAL">Logged Normal</option>
              </select>
              <select
                className="input"
                style={{ padding: '6px 12px', fontSize: 12, width: 'auto' }}
                value={filterResident}
                onChange={e => setFilterResident(e.target.value)}
              >
                <option value="">All Residents</option>
                <option value="R1">R1</option>
                <option value="R2">R2</option>
              </select>
              {(filterTier || filterResident) && (
                <button className="btn btn-secondary btn-sm" onClick={() => { setFilterTier(''); setFilterResident(''); }}>
                  Clear
                </button>
              )}
              <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                {filteredAlerts.length} alerts
              </span>
            </div>

            {loading ? (
              <div style={{ padding: 32, textAlign: 'center' }}>
                <div className="spinner" />
              </div>
            ) : filteredAlerts.length === 0 ? (
              <div className="empty-state">
                <ShieldCheck size={36} color="var(--success)" />
                <p style={{ color: 'var(--success)' }}>No alerts found. Run prioritisation to generate alerts.</p>
              </div>
            ) : (
              filteredAlerts.map(alert => (
                <AlertCard key={alert.alert_id} alert={alert} onReview={handleReview} />
              ))
            )}
          </div>

          {/* Actions panel */}
          <div>
            {/* Run Prioritisation */}
            <div className="card mb-6">
              <div className="card-header">
                <div className="card-title"><Zap size={16} /> Run Prioritisation</div>
              </div>
              <div style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                  Resident
                </label>
                <select
                  className="input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  value={prioResident}
                  onChange={e => setPrioResident(e.target.value)}
                >
                  <option value="R1">R1</option>
                  <option value="R2">R2</option>
                </select>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.5 }}>
                Computes deviation, evidence, and priority for today's activity.
                Thresholds: τ=0.25, τ_E=0.40
              </div>
              <button
                className="btn btn-primary"
                style={{ width: '100%' }}
                onClick={handlePrioritise}
                disabled={prioritising}
              >
                {prioritising
                  ? <><div className="spinner" style={{ width: 14, height: 14 }} /> Computing…</>
                  : <><Play size={14} /> Prioritise Now</>
                }
              </button>
            </div>

            {/* Anomaly Injection */}
            <div className="card">
              <div className="card-header">
                <div className="card-title"><AlertTriangle size={16} /> Synthetic Injection</div>
                <span className="badge badge-demo">TEST</span>
              </div>
              <div style={{ marginBottom: 10 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                  Anomaly Type
                </label>
                <select
                  className="input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  value={injectType}
                  onChange={e => setInjectType(e.target.value)}
                >
                  {['TIME_SHIFT', 'MISSING_ACTIVITY', 'PROLONGED', 'NIGHT_ACTIVITY', 'FREQ_CHANGE'].map(t => (
                    <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </div>
              <div style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                  Severity
                </label>
                <select
                  className="input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  value={injectSeverity}
                  onChange={e => setInjectSeverity(e.target.value)}
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.5 }}>
                Adds synthetic anomaly events (labeled) without modifying original data.
              </div>
              <button
                className="btn btn-secondary"
                style={{ width: '100%' }}
                onClick={handleInject}
                disabled={injecting}
              >
                {injecting
                  ? <><div className="spinner" style={{ width: 14, height: 14 }} /> Injecting…</>
                  : <><Play size={14} /> Inject Anomaly</>
                }
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
