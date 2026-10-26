/**
 * Live Sensor Monitoring Page
 * Shows real-time sensor event stream from the Data Layer.
 */
import { useState, useEffect, useRef } from 'react';
import { Wifi, RefreshCw, Play, Square, Filter } from 'lucide-react';
import { getSensorEvents, simulateSensorEvents, getSensorMetadata } from '../services/api';
import { useToast } from '../hooks/useToast';

const SOURCE_LABELS = {
  simulator: { label: 'Simulator', class: 'badge-demo' },
  dataset: { label: 'Dataset', class: 'badge-cyan' },
  api: { label: 'API', class: 'badge-success' },
};

function StateTag({ state }) {
  const s = (state || '').toUpperCase();
  const cls =
    s === 'ON' ? 'on' : s === 'OFF' ? 'off' : s === 'OPEN' ? 'open' : s === 'CLOSED' ? 'closed' : '';
  return <span className={`event-state ${cls}`}>{state}</span>;
}

export default function LiveSensorMonitoring() {
  const { addToast } = useToast();
  const [events, setEvents] = useState([]);
  const [metadata, setMetadata] = useState([]);
  const [total, setTotal] = useState(0);
  const [streaming, setStreaming] = useState(false);
  const [filters, setFilters] = useState({ resident_id: '', sensor_id: '', source: '' });
  const [loading, setLoading] = useState(true);
  const streamRef = useRef(null);

  const fetchEvents = async () => {
    try {
      const params = { limit: 100, offset: 0 };
      if (filters.resident_id) params.resident_id = filters.resident_id;
      if (filters.sensor_id) params.sensor_id = filters.sensor_id;
      if (filters.source) params.source = filters.source;
      const data = await getSensorEvents(params);
      setEvents(data.events || []);
      setTotal(data.total || 0);
    } catch (err) {
      addToast('Failed to fetch sensor events', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    Promise.all([fetchEvents(), getSensorMetadata().then(d => setMetadata(d.sensors || []))]);
  }, []);

  useEffect(() => {
    if (!streaming) return;
    streamRef.current = setInterval(async () => {
      try {
        await simulateSensorEvents(3, 'R1');
        await fetchEvents();
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(streamRef.current);
  }, [streaming, filters]);

  const toggleStream = () => {
    setStreaming(s => !s);
    if (!streaming) addToast('🟢 Live sensor stream started', 'success');
    else addToast('🔴 Stream paused', 'info');
  };

  const handleFilter = (k, v) => {
    setFilters(f => ({ ...f, [k]: v }));
  };

  useEffect(() => {
    fetchEvents();
  }, [filters]);

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Live Sensor Monitoring</h2>
            <p>Real-time sensor event stream — Layer 1: Data Layer</p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {streaming && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--success)' }}>
                <span className="pulse-dot" /> Live
              </span>
            )}
            <button className="btn btn-secondary btn-sm" onClick={fetchEvents}>
              <RefreshCw size={14} /> Refresh
            </button>
            <button
              className={`btn btn-sm ${streaming ? 'btn-danger' : 'btn-primary'}`}
              onClick={toggleStream}
            >
              {streaming ? <><Square size={14} /> Stop Stream</> : <><Play size={14} /> Start Stream</>}
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        {/* Stats */}
        <div className="stats-grid mb-4" style={{ gridTemplateColumns: 'repeat(3,1fr)' }}>
          {[
            { label: 'Total Events', value: total, color: 'var(--primary-light)' },
            { label: 'Showing', value: events.length, color: 'var(--accent-cyan)' },
            { label: 'Known Sensors', value: metadata.length, color: 'var(--success)' },
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
          <label>Resident:</label>
          <select value={filters.resident_id} onChange={e => handleFilter('resident_id', e.target.value)}>
            <option value="">All</option>
            <option>R1</option>
            <option>R2</option>
          </select>
          <label>Source:</label>
          <select value={filters.source} onChange={e => handleFilter('source', e.target.value)}>
            <option value="">All</option>
            <option value="simulator">Simulator</option>
            <option value="dataset">Dataset</option>
            <option value="api">API</option>
          </select>
          <label>Sensor ID:</label>
          <input
            placeholder="e.g. PIR_KITCHEN"
            value={filters.sensor_id}
            onChange={e => handleFilter('sensor_id', e.target.value)}
            style={{ maxWidth: 160 }}
          />
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 12, color: 'var(--text-muted)' }}>
          <span><span style={{ borderLeft: '3px solid var(--demo)', paddingLeft: 6 }}>Simulator</span></span>
          <span><span style={{ borderLeft: '3px solid var(--accent-cyan)', paddingLeft: 6 }}>Dataset Upload</span></span>
          <span><span style={{ borderLeft: '3px solid var(--accent-emerald)', paddingLeft: 6 }}>API Ingestion</span></span>
        </div>

        {/* Event table */}
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Sensor ID</th>
                <th>Type</th>
                <th>State</th>
                <th>Resident</th>
                <th>Activity</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                  <div className="spinner" style={{ margin: '0 auto' }} />
                </td></tr>
              ) : events.length === 0 ? (
                <tr><td colSpan={7}>
                  <div className="empty-state">
                    <Wifi size={32} />
                    <p>No sensor events found. Use <strong>Start Stream</strong> or upload a dataset.</p>
                  </div>
                </td></tr>
              ) : events.map(ev => (
                <tr key={ev.id} className={`event-row source-${ev.source}`}
                  style={{ display: 'table-row', animation: 'none' }}>
                  <td className="event-timestamp">
                    {new Date(ev.timestamp).toLocaleString()}
                  </td>
                  <td className="event-sensor-id">{ev.sensor_id}</td>
                  <td><span className="badge badge-neutral">{ev.sensor_type}</span></td>
                  <td><StateTag state={ev.sensor_state} /></td>
                  <td style={{ fontWeight: 600 }}>{ev.resident_id || '—'}</td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {ev.activity_label ? ev.activity_label.replace(/_/g, ' ') : '—'}
                  </td>
                  <td>
                    <span className={`badge ${SOURCE_LABELS[ev.source]?.class || 'badge-neutral'}`}>
                      {SOURCE_LABELS[ev.source]?.label || ev.source}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Sensor metadata */}
        {metadata.length > 0 && (
          <div className="card mt-4">
            <div className="card-header">
              <div className="card-title"><Wifi size={16} /> Sensor Registry ({metadata.length} sensors)</div>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {metadata.map(s => (
                <div key={s.sensor_id} style={{
                  background: 'var(--bg-surface)', border: '1px solid var(--border)',
                  borderRadius: 8, padding: '6px 12px', fontSize: 11,
                }}>
                  <div style={{ fontWeight: 700, color: 'var(--primary-light)', fontFamily: 'var(--font-mono)' }}>
                    {s.sensor_id}
                  </div>
                  <div style={{ color: 'var(--text-muted)' }}>{s.sensor_type} · {s.location}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
