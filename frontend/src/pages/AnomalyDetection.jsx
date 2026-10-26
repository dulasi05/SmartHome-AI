/**
 * Anomaly Detection Page
 * Displays anomaly alerts with severity, reason, sensors, and status controls.
 */
import { useState, useEffect } from 'react';
import { AlertTriangle, RefreshCw, CheckCircle, ShieldAlert, Filter } from 'lucide-react';
import { getAnomalyAlerts, updateAlertStatus } from '../services/api';
import { useToast } from '../hooks/useToast';

const SEVERITY_CONFIG = {
  low: { color: 'var(--info)', bg: 'var(--info-bg)', badge: 'badge-info', icon: '🔵' },
  medium: { color: 'var(--warning)', bg: 'var(--warning-bg)', badge: 'badge-warning', icon: '🟡' },
  high: { color: 'var(--error)', bg: 'var(--error-bg)', badge: 'badge-error', icon: '🔴' },
  critical: { color: 'var(--error)', bg: 'rgba(244,63,94,0.15)', badge: 'badge-error', icon: '🚨' },
};

const STATUS_CONFIG = {
  active: { color: 'var(--error)', label: 'Active' },
  acknowledged: { color: 'var(--warning)', label: 'Acknowledged' },
  resolved: { color: 'var(--success)', label: 'Resolved' },
};

function AnomalyCard({ alert, onStatusChange }) {
  const sev = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.low;
  const status = STATUS_CONFIG[alert.status] || STATUS_CONFIG.active;

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: `1px solid ${sev.color}30`,
      borderLeft: `4px solid ${sev.color}`,
      borderRadius: 12,
      padding: 16,
      marginBottom: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>{sev.icon}</span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: sev.color }}>
              {alert.severity.toUpperCase()} SEVERITY
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {new Date(alert.timestamp).toLocaleString()}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={`badge ${
            alert.status === 'active' ? 'badge-error' :
            alert.status === 'acknowledged' ? 'badge-warning' : 'badge-success'
          }`}>
            {STATUS_CONFIG[alert.status]?.label || alert.status}
          </span>
          <span className="badge badge-demo">⚠️ DEMO Score</span>
        </div>
      </div>

      {/* Anomaly score */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Anomaly Score</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: sev.color }}>
            {(alert.anomaly_score * 100).toFixed(0)}%
          </span>
        </div>
        <div className="progress-bar">
          <div
            className="progress-fill"
            style={{
              width: `${alert.anomaly_score * 100}%`,
              background: `linear-gradient(90deg, ${sev.color}, var(--accent-amber))`,
            }}
          />
        </div>
      </div>

      {/* Reason */}
      <div style={{
        background: 'var(--bg-surface)', borderRadius: 8, padding: '8px 12px',
        fontSize: 12, color: 'var(--text-secondary)', marginBottom: 10,
        border: '1px solid var(--border)',
      }}>
        <strong style={{ color: 'var(--text-primary)' }}>Reason:</strong> {alert.reason}
      </div>

      {/* Affected sensors */}
      {alert.affected_sensors?.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 5 }}>Affected Sensors:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {alert.affected_sensors.map(s => (
              <span key={s} style={{
                fontFamily: 'var(--font-mono)', fontSize: 11,
                background: 'var(--bg-surface)', border: '1px solid var(--border)',
                borderRadius: 4, padding: '2px 8px', color: 'var(--primary-light)',
              }}>{s}</span>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      {alert.status !== 'resolved' && (
        <div style={{ display: 'flex', gap: 8 }}>
          {alert.status === 'active' && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onStatusChange(alert.id, 'acknowledged')}
            >
              <CheckCircle size={13} /> Acknowledge
            </button>
          )}
          <button
            className="btn btn-sm"
            style={{ background: 'var(--success-bg)', color: 'var(--success)' }}
            onClick={() => onStatusChange(alert.id, 'resolved')}
          >
            ✅ Resolve
          </button>
        </div>
      )}
    </div>
  );
}

export default function AnomalyDetection() {
  const { addToast } = useToast();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ severity: '', status: '', resident_id: '' });

  const fetchAlerts = async () => {
    try {
      const params = { limit: 50 };
      if (filters.severity) params.severity = filters.severity;
      if (filters.status) params.status = filters.status;
      if (filters.resident_id) params.resident_id = filters.resident_id;
      const data = await getAnomalyAlerts(params);
      setAlerts(data.alerts || []);
    } catch {
      addToast('Failed to load anomaly alerts', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAlerts(); }, [filters]);

  const handleStatusChange = async (alertId, status) => {
    try {
      await updateAlertStatus(alertId, status);
      addToast(`Alert ${status}`, 'success');
      await fetchAlerts();
    } catch {
      addToast('Failed to update alert', 'error');
    }
  };

  const activeCount = alerts.filter(a => a.status === 'active').length;
  const highCount = alerts.filter(a => a.severity === 'high' || a.severity === 'critical').length;

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Anomaly Detection</h2>
            <p>Unusual activity pattern alerts — Layer 3: Intelligence (Demo Mode)</p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-secondary btn-sm" onClick={fetchAlerts}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        <div className="demo-banner">
          <ShieldAlert size={16} />
          <strong>⚠️ DEMO MODE:</strong> Anomaly scores are computed using statistical heuristics, not the real model.
          All scores are labeled <code>is_demo: true</code>.
        </div>

        {/* Stats */}
        <div className="stats-grid mb-4" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
          {[
            { label: 'Total Alerts', value: alerts.length, color: 'var(--text-primary)' },
            { label: 'Active', value: activeCount, color: 'var(--error)' },
            { label: 'High Severity', value: highCount, color: 'var(--warning)' },
            { label: 'Resolved', value: alerts.filter(a => a.status === 'resolved').length, color: 'var(--success)' },
          ].map(s => (
            <div key={s.label} className="stat-card">
              <div className="stat-value" style={{ color: s.color, fontSize: 24 }}>{s.value}</div>
              <div className="stat-label">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="filters-bar">
          <Filter size={14} color="var(--text-muted)" />
          <label>Severity:</label>
          <select value={filters.severity} onChange={e => setFilters(f => ({ ...f, severity: e.target.value }))}>
            <option value="">All</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <label>Status:</label>
          <select value={filters.status} onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}>
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
          <label>Resident:</label>
          <select value={filters.resident_id} onChange={e => setFilters(f => ({ ...f, resident_id: e.target.value }))}>
            <option value="">All</option>
            <option value="R1">R1</option>
            <option value="R2">R2</option>
          </select>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <div className="spinner" style={{ margin: '0 auto' }} />
          </div>
        ) : alerts.length === 0 ? (
          <div className="empty-state">
            <AlertTriangle size={48} color="var(--text-muted)" />
            <p>No anomaly alerts found. Run predictions to generate anomaly data.</p>
          </div>
        ) : (
          alerts.map(alert => (
            <AnomalyCard key={alert.id} alert={alert} onStatusChange={handleStatusChange} />
          ))
        )}
      </div>
    </div>
  );
}
