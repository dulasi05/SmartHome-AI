/**
 * Routine Analysis Page
 * Shows daily activity profiles, historical charts, and unusual deviations.
 */
import { useState, useEffect } from 'react';
import { BookOpen, RefreshCw, TrendingUp } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell
} from 'recharts';
import { getRoutineProfile, getActivityHistory, getPredictions } from '../services/api';
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

export default function RoutineAnalysis() {
  const { addToast } = useToast();
  const [residentId, setResidentId] = useState(
    () => localStorage.getItem('smartHome_residentId') || 'R1'
  );
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState(null);
  const [recentPreds, setRecentPreds] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [p, h, preds] = await Promise.all([
        getRoutineProfile(residentId),
        getActivityHistory(residentId, 48),
        getPredictions({ resident_id: residentId, limit: 100 }),
      ]);
      setProfile(p);
      setHistory(h);
      setRecentPreds(preds.predictions || []);
    } catch (err) {
      addToast('Failed to load routine data', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [residentId]);

  // Build hourly activity chart from predictions
  const hourlyCounts = {};
  recentPreds.forEach(p => {
    const h = new Date(p.timestamp).getHours();
    if (!hourlyCounts[h]) hourlyCounts[h] = {};
    const act = p.predicted_activity;
    hourlyCounts[h][act] = (hourlyCounts[h][act] || 0) + 1;
  });

  const hourlyChartData = Array.from({ length: 24 }, (_, h) => {
    const acts = hourlyCounts[h] || {};
    const topAct = Object.entries(acts).sort((a, b) => b[1] - a[1])[0];
    return {
      hour: `${h.toString().padStart(2, '0')}:00`,
      activity: topAct ? topAct[0] : null,
      count: topAct ? topAct[1] : 0,
      color: topAct ? ACTIVITY_COLORS[topAct[0]] || '#94a3b8' : '#1e293b',
    };
  });

  // Sequence from profile
  const sequence = profile?.activity_sequence?.slice(-20) || [];

  // Hourly distribution from profile
  const hourlyDist = profile?.hourly_distribution || {};

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Routine Analysis</h2>
            <p>Daily activity profiles and historical patterns per resident</p>
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
            <button className="btn btn-secondary btn-sm" onClick={fetchData}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <div className="spinner" style={{ margin: '0 auto 12px' }} />
            <div className="text-muted">Loading routine data…</div>
          </div>
        ) : (
          <>
            {/* Summary stats */}
            <div className="stats-grid mb-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
              <div className="stat-card">
                <div className="stat-value" style={{ color: 'var(--primary-light)', fontSize: 24 }}>
                  {profile?.total_events || 0}
                </div>
                <div className="stat-label">Recorded Events</div>
              </div>
              <div className="stat-card">
                <div className="stat-value" style={{ color: 'var(--accent-cyan)', fontSize: 24 }}>
                  {Object.keys(hourlyDist).length}
                </div>
                <div className="stat-label">Active Hours</div>
              </div>
              <div className="stat-card">
                <div className="stat-value" style={{ color: 'var(--success)', fontSize: 24 }}>
                  {recentPreds.length}
                </div>
                <div className="stat-label">Predictions (48h)</div>
              </div>
            </div>

            {/* Hourly activity bar chart */}
            <div className="card mb-4">
              <div className="card-header">
                <div className="card-title"><TrendingUp size={16} /> Activity Frequency by Hour</div>
              </div>
              {hourlyChartData.some(d => d.count > 0) ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={hourlyChartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="hour" tick={{ fontSize: 10 }} interval={2} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.[0]) return null;
                        const d = payload[0].payload;
                        return (
                          <div style={{
                            background: 'var(--bg-card)', border: '1px solid var(--border)',
                            borderRadius: 8, padding: '8px 12px', fontSize: 12,
                          }}>
                            <div style={{ fontWeight: 700 }}>{d.hour}</div>
                            {d.activity && (
                              <div style={{ color: d.color }}>
                                {ACTIVITY_EMOJIS[d.activity]} {d.activity?.replace(/_/g, ' ')}
                              </div>
                            )}
                            <div style={{ color: 'var(--text-muted)' }}>{d.count} predictions</div>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {hourlyChartData.map((d, i) => (
                        <Cell key={i} fill={d.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="empty-state"><p>Run predictions to see hourly distribution</p></div>
              )}
            </div>

            <div className="grid-2">
              {/* Activity sequence timeline */}
              <div className="card">
                <div className="card-header">
                  <div className="card-title"><BookOpen size={16} /> Recent Activity Sequence</div>
                  <span className="badge badge-neutral">{sequence.length} events</span>
                </div>
                {sequence.length === 0 ? (
                  <div className="empty-state"><p>No activity sequence yet</p></div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 360, overflowY: 'auto' }}>
                    {sequence.map((entry, i) => (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        padding: '7px 10px', borderRadius: 8, background: 'var(--bg-surface)',
                        borderLeft: `3px solid ${ACTIVITY_COLORS[entry.activity] || '#94a3b8'}`,
                      }}>
                        <span style={{ fontSize: 18 }}>{ACTIVITY_EMOJIS[entry.activity] || '🏠'}</span>
                        <div style={{ flex: 1 }}>
                          <div style={{
                            fontSize: 13, fontWeight: 600, textTransform: 'capitalize',
                            color: ACTIVITY_COLORS[entry.activity] || 'var(--text-primary)',
                          }}>
                            {entry.activity?.replace(/_/g, ' ')}
                          </div>
                          {entry.timestamp && (
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                              {new Date(entry.timestamp).toLocaleTimeString()}
                            </div>
                          )}
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--accent-cyan)', fontWeight: 600 }}>
                          {entry.confidence ? `${(entry.confidence * 100).toFixed(0)}%` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Hourly distribution from profile */}
              <div className="card">
                <div className="card-header">
                  <div className="card-title">Hourly Activity Profile</div>
                </div>
                {Object.keys(hourlyDist).length === 0 ? (
                  <div className="empty-state"><p>No profile data yet</p></div>
                ) : (
                  <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                    {Object.entries(hourlyDist).sort((a, b) => parseInt(a[0]) - parseInt(b[0])).map(([hour, info]) => (
                      <div key={hour} style={{
                        display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0',
                        borderBottom: '1px solid var(--border)',
                      }}>
                        <div style={{
                          width: 40, fontFamily: 'var(--font-mono)', fontSize: 12,
                          color: 'var(--text-muted)', flexShrink: 0,
                        }}>
                          {parseInt(hour).toString().padStart(2, '0')}:00
                        </div>
                        <span style={{ fontSize: 18 }}>
                          {ACTIVITY_EMOJIS[info.most_common] || '🏠'}
                        </span>
                        <div style={{ flex: 1, fontSize: 13, textTransform: 'capitalize',
                          color: ACTIVITY_COLORS[info.most_common] || 'var(--text-primary)',
                          fontWeight: 500,
                        }}>
                          {info.most_common?.replace(/_/g, ' ')}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {Object.values(info.activity_counts || {}).reduce((a, b) => a + b, 0)} events
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
