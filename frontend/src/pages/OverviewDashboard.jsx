/**
 * Overview Dashboard Page — Layer 5: Presentation Layer
 * Displays live stats, current activity, anomalies, and pipeline health.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Activity, Wifi, Database, AlertTriangle, TrendingUp,
  RefreshCw, Play, Cpu, CheckCircle2, Clock
} from 'lucide-react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer
} from 'recharts';
import {
  getDashboardStats, simulateSensorEvents, runPrediction,
  getActivityHistory
} from '../services/api';
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
  reading: '📖', resting: '🛋️', using_phone: '📱', other: '🏠',
};

const SEVERITY_COLOR = { low: 'info', medium: 'warning', high: 'error', critical: 'error' };

export default function OverviewDashboard() {
  const { addToast } = useToast();
  const [stats, setStats] = useState(null);
  const [activityHistory, setActivityHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        getDashboardStats(24),
        getActivityHistory('R1', 12),
      ]);
      setStats(s);
      setActivityHistory(h);
    } catch (err) {
      addToast('Failed to load dashboard data. Is the backend running?', 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleQuickSim = async () => {
    setRunning(true);
    try {
      await simulateSensorEvents(15, 'R1');
      await runPrediction('R1', 30);
      addToast('✅ Simulated events and ran prediction!', 'success');
      await fetchData();
    } catch (err) {
      addToast(`Error: ${err.response?.data?.detail || err.message}`, 'error');
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 32, display: 'flex', alignItems: 'center', gap: 12 }}>
        <div className="spinner" />
        <span className="text-muted">Loading dashboard…</span>
      </div>
    );
  }

  // Prepare pie data
  const pieData = stats?.activity_distribution
    ? Object.entries(stats.activity_distribution).map(([name, value]) => ({
        name: name.replace(/_/g, ' '), value, key: name,
      }))
    : [];



  const currentAct = stats?.current_activity;
  const activeAlerts = stats?.anomalies?.active || 0;

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Overview Dashboard</h2>
            <p>Real-time smart home activity monitoring — data retrieved from SQLite storage</p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-secondary btn-sm" onClick={fetchData}>
              <RefreshCw size={14} /> Refresh
            </button>
            <button className="btn btn-primary btn-sm" onClick={handleQuickSim} disabled={running}>
              {running ? <div className="spinner" style={{ width: 14, height: 14 }} /> : <Play size={14} />}
              Quick Simulate
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        {/* Demo banner */}
        <div className="demo-banner">
          <Cpu size={16} />
          <strong>DEMO MODE:</strong> Predictions are heuristic simulations. The real Powerformer/WC-MHA model is not yet integrated.
          All predictions are clearly labeled <code style={{ fontSize: 11 }}>is_demo: true</code> in the database.
        </div>

        {/* Stats row */}
        <div className="stats-grid">
          <div className="stat-card" style={{ '--gradient': 'linear-gradient(90deg, #5b8dee, #a855f7)' }}>
            <div className="stat-icon" style={{ background: 'rgba(91,141,238,0.15)' }}>
              <Wifi size={20} color="var(--primary)" />
            </div>
            <div className="stat-value" style={{ color: 'var(--primary-light)' }}>
              {stats?.sensor_events?.total?.toLocaleString() || 0}
            </div>
            <div className="stat-label">Total Sensor Events</div>
            <div className="stat-change" style={{ fontSize: 11 }}>
              {stats?.sensor_events?.recent || 0} in 24h · {stats?.sensor_events?.hardware || 0} hardware · {stats?.sensor_events?.simulated || 0} simulated · {stats?.sensor_events?.from_dataset || 0} dataset
            </div>
          </div>

          <div className="stat-card" style={{ '--gradient': 'linear-gradient(90deg, #10b981, #06b6d4)' }}>
            <div className="stat-icon" style={{ background: 'rgba(16,185,129,0.15)' }}>
              <Activity size={20} color="var(--success)" />
            </div>
            <div className="stat-value" style={{ color: 'var(--success)' }}>
              {stats?.predictions?.total?.toLocaleString() || 0}
            </div>
            <div className="stat-label">Predictions Made</div>
            <div className="stat-change">{stats?.predictions?.recent_count || 0} in last 24h</div>
          </div>

          <div className="stat-card" style={{ '--gradient': 'linear-gradient(90deg, #f59e0b, #f97316)' }}>
            <div className="stat-icon" style={{ background: 'rgba(245,158,11,0.15)' }}>
              <AlertTriangle size={20} color="var(--warning)" />
            </div>
            <div className="stat-value" style={{ color: activeAlerts > 0 ? 'var(--error)' : 'var(--warning)' }}>
              {activeAlerts}
            </div>
            <div className="stat-label">Active Alerts</div>
            <div className="stat-change">{stats?.anomalies?.total || 0} total anomalies</div>
          </div>

          <div className="stat-card" style={{ '--gradient': 'linear-gradient(90deg, #a855f7, #5b8dee)' }}>
            <div className="stat-icon" style={{ background: 'rgba(168,85,247,0.15)' }}>
              <Database size={20} color="var(--demo)" />
            </div>
            <div className="stat-value" style={{ color: 'var(--demo)' }}>
              {stats?.datasets?.upload_count || 0}
            </div>
            <div className="stat-label">Uploaded Datasets</div>
            <div className="stat-change">ARAS / CASAS / Custom</div>
          </div>
        </div>

        {/* Current activity + Recent alerts */}
        <div className="grid-2-1 mb-6">
          {/* Current activity */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Activity size={16} />
                Current Detected Activity
              </div>
              {currentAct?.is_demo && (
                <span className="badge badge-demo">⚠️ DEMO</span>
              )}
            </div>
            {currentAct ? (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
                  <div style={{
                    width: 72, height: 72, borderRadius: 18,
                    background: `${ACTIVITY_COLORS[currentAct.activity] || '#5b8dee'}20`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 36,
                    border: `2px solid ${ACTIVITY_COLORS[currentAct.activity] || '#5b8dee'}40`,
                  }}>
                    {ACTIVITY_EMOJIS[currentAct.activity] || '🏠'}
                  </div>
                  <div>
                    <div style={{
                      fontSize: 22, fontWeight: 800,
                      color: ACTIVITY_COLORS[currentAct.activity] || 'var(--primary-light)',
                      textTransform: 'capitalize',
                    }}>
                      {currentAct.activity?.replace(/_/g, ' ')}
                    </div>
                    <div className="text-muted text-sm">Resident: {currentAct.resident_id}</div>
                    <div className="text-muted text-xs" style={{ marginTop: 4 }}>
                      <Clock size={11} style={{ display: 'inline', marginRight: 4 }} />
                      {new Date(currentAct.timestamp).toLocaleTimeString()}
                    </div>
                  </div>
                </div>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span className="text-sm text-secondary">Confidence</span>
                    <span className="confidence-number" style={{ fontSize: 20 }}>
                      {(currentAct.confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{
                        width: `${currentAct.confidence * 100}%`,
                        background: `linear-gradient(90deg, ${ACTIVITY_COLORS[currentAct.activity] || 'var(--primary)'}, var(--accent-cyan))`,
                      }}
                    />
                  </div>
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
                  Model: {currentAct.model_name}
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <Activity size={32} />
                <p>No predictions yet. Click <strong>Quick Simulate</strong> to start.</p>
              </div>
            )}
          </div>

          {/* Recent Alerts */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <AlertTriangle size={16} />
                Recent Alerts
              </div>
              {activeAlerts > 0 && <span className="badge badge-error">{activeAlerts} active</span>}
            </div>
            {stats?.anomalies?.recent?.length > 0 ? (
              stats.anomalies.recent.map(alert => (
                <div key={alert.id} className={`alert-card severity-${alert.severity}`}>
                  <AlertTriangle size={16} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>{alert.reason}</div>
                    <div style={{ fontSize: 11, opacity: 0.7 }}>
                      {new Date(alert.timestamp).toLocaleString()} · {alert.status}
                    </div>
                  </div>
                  <span className={`badge badge-${SEVERITY_COLOR[alert.severity] || 'neutral'}`}>
                    {alert.severity}
                  </span>
                </div>
              ))
            ) : (
              <div className="empty-state">
                <CheckCircle2 size={28} color="var(--success)" />
                <p style={{ color: 'var(--success)' }}>No active alerts</p>
              </div>
            )}
          </div>
        </div>

        {/* Charts */}
        <div className="grid-2 mb-6">
          {/* Activity distribution pie */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <TrendingUp size={16} />
                Activity Distribution (24h)
              </div>
            </div>
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    innerRadius={40}
                    paddingAngle={3}
                  >
                    {pieData.map(entry => (
                      <Cell
                        key={entry.key}
                        fill={ACTIVITY_COLORS[entry.key] || '#94a3b8'}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(val, name) => [val, name]}
                    contentStyle={{
                      background: 'var(--bg-card)', border: '1px solid var(--border)',
                      borderRadius: 8, fontSize: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-state"><p>Run predictions to see activity distribution</p></div>
            )}
          </div>

          {/* Pipeline health */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Cpu size={16} />
                Pipeline Health
              </div>
            </div>
            {stats?.pipeline_status?.layers?.map(layer => (
              <div key={layer.id} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 0', borderBottom: '1px solid var(--border)',
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 8,
                  background: 'linear-gradient(135deg, var(--primary), var(--accent-purple))',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 800, color: 'white', flexShrink: 0,
                }}>
                  {layer.id}
                </div>
                <div style={{ flex: 1, fontSize: 13, fontWeight: 500 }}>{layer.name}</div>
                <span className={`badge badge-${
                  layer.status === 'connected' ? 'success' :
                  layer.status === 'demo' ? 'demo' :
                  layer.status === 'running' ? 'info' :
                  layer.status === 'ready' ? 'success' : 'neutral'
                }`}>
                  {layer.status_label}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Residents */}
        {stats?.residents?.length > 0 && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Active Residents</div>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              {stats.residents.map(r => (
                <div key={r} style={{
                  background: 'var(--primary-glow)', border: '1px solid rgba(91,141,238,0.25)',
                  borderRadius: 10, padding: '8px 16px', fontSize: 13, fontWeight: 600,
                  color: 'var(--primary-light)',
                }}>
                  👤 {r}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
