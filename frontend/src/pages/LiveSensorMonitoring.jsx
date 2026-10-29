/**
 * Live Sensor Monitoring Page — Layer 1: Data Layer
 * Displays real-time physical sensor data, live motion status, device connection diagnostics,
 * and sensor stream history with source filtering.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Wifi, RefreshCw, Play, Square, Filter, Cpu,
  Radio, AlertCircle, CheckCircle2, MapPin, Gauge,
  Activity, Send, Clock, ServerOff
} from 'lucide-react';
import {
  getSensorEvents,
  simulateSensorEvents,
  getSensorMetadata,
  getLiveSensorStatus,
  getDeviceStatus,
  postSensorEvent,
  sendDevTestHardwareEvent
} from '../services/api';
import { useToast } from '../hooks/useToast';

const SOURCE_LABELS = {
  hardware: { label: 'Physical Hardware', class: 'badge-hardware', icon: Radio },
  simulator: { label: 'Simulator (Demo)', class: 'badge-demo', icon: Cpu },
  dataset: { label: 'Dataset Import', class: 'badge-cyan', icon: Wifi },
  api: { label: 'REST API', class: 'badge-info', icon: Send },
};

function StateTag({ state }) {
  const s = (state || '').toUpperCase();
  const cls =
    s === 'ON' || s === 'DETECTED' ? 'on' :
    s === 'OFF' || s === 'CLEAR' ? 'off' :
    s === 'OPEN' ? 'open' :
    s === 'CLOSED' ? 'closed' : '';
  return <span className={`event-state ${cls}`}>{state}</span>;
}

function formatRelativeTime(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}

export default function LiveSensorMonitoring() {
  const { addToast } = useToast();
  const [events, setEvents] = useState([]);
  const [metadata, setMetadata] = useState([]);
  const [liveStatus, setLiveStatus] = useState(null);
  const [deviceStatus, setDeviceStatus] = useState(null);
  const [total, setTotal] = useState(0);
  const [polling, setPolling] = useState(true);
  const [filters, setFilters] = useState({ resident_id: '', sensor_id: '', source: '' });
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(null);

  // Quick Hardware Test Event State
  const [showTestModal, setShowTestModal] = useState(false);
  const [testPayload, setTestPayload] = useState({
    sensor_id: 'PIR_LIVING',
    sensor_type: 'motion',
    sensor_state: 'ON',
    resident_id: 'R1',
    source: 'hardware',
    raw_value: 1.0,
    device_id: 'esp32-node-01'
  });
  const [submittingTest, setSubmittingTest] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const pollRef = useRef(null);

  const fetchAllData = useCallback(async () => {
    try {
      const params = { limit: 100, offset: 0 };
      if (filters.resident_id) params.resident_id = filters.resident_id;
      if (filters.sensor_id) params.sensor_id = filters.sensor_id;
      if (filters.source) params.source = filters.source;

      const [eventsData, liveData, devData, metaData] = await Promise.all([
        getSensorEvents(params),
        getLiveSensorStatus().catch(() => null),
        getDeviceStatus().catch(() => null),
        getSensorMetadata().catch(() => ({ sensors: [] }))
      ]);

      setEvents(eventsData.events || []);
      setTotal(eventsData.total || 0);
      if (liveData) setLiveStatus(liveData);
      if (devData) setDeviceStatus(devData);
      if (metaData && metaData.sensors) setMetadata(metaData.sensors);
      setApiError(null);
    } catch (err) {
      setApiError(err.message || 'Unable to connect to SmartHome API');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  // Initial load
  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  // Real-time polling loop
  useEffect(() => {
    if (!polling) return;
    pollRef.current = setInterval(() => {
      fetchAllData();
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [polling, fetchAllData]);

  const togglePolling = () => {
    setPolling(p => !p);
    if (!polling) addToast('🟢 Real-time stream polling activated (3s)', 'success');
    else addToast('⏸️ Polling paused', 'info');
  };

  const handleFilter = (k, v) => {
    setFilters(f => ({ ...f, [k]: v }));
  };

  const handleSimulate = async () => {
    try {
      await simulateSensorEvents(5, 'R1');
      addToast('Generated 5 simulated demo sensor events (labeled simulator)', 'success');
      await fetchAllData();
    } catch {
      addToast('Failed to trigger simulation', 'error');
    }
  };

  const handleSendTestHardwareEvent = async (e) => {
    e.preventDefault();
    setSubmittingTest(true);
    try {
      const res = await sendDevTestHardwareEvent(testPayload);
      setTestResult(res);
      if (res.status === 'duplicate_ignored') {
        addToast(`ℹ️ ${res.message || 'Duplicate event suppressed'}`, 'warning');
      } else {
        addToast(`✅ Ingested hardware event: ${res.sensor_id} (${res.sensor_state})`, 'success');
      }
      await fetchAllData();
    } catch (err) {
      addToast(`Error: ${err.response?.data?.detail || err.message}`, 'error');
    } finally {
      setSubmittingTest(false);
    }
  };

  const motionInfo = liveStatus?.motion_status;
  const isMotionDetected = motionInfo?.detected;
  const latestMotionEvent = motionInfo?.latest_event;
  const onlineDevices = deviceStatus?.devices?.filter(d => d.is_online) || [];
  const hardwareConfigured = deviceStatus?.hardware_configured || false;
  const isHardwareOnline = liveStatus?.hardware_online || onlineDevices.length > 0;

  return (
    <div>
      {/* Page Header */}
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Live Sensor Monitoring</h2>
            <p>Real-time physical IoT sensors and home activity stream</p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {polling && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--success)' }}>
                <span className="pulse-dot" /> Live Polling
              </span>
            )}
            <button className="btn btn-secondary btn-sm" onClick={fetchAllData}>
              <RefreshCw size={14} /> Refresh
            </button>
            <button
              className={`btn btn-sm ${polling ? 'btn-danger' : 'btn-primary'}`}
              onClick={togglePolling}
            >
              {polling ? <><Square size={14} /> Pause Polling</> : <><Play size={14} /> Resume Polling</>}
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => setShowTestModal(true)}>
              <Radio size={14} /> Test Hardware Event
            </button>
          </div>
        </div>
      </div>

      <div className="page-body">
        {/* API Error / Disconnected Banner */}
        {apiError && (
          <div className="alert-card severity-critical" style={{ marginBottom: 20 }}>
            <ServerOff size={22} color="var(--error)" />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--error)' }}>
                Backend Disconnected or Unreachable
              </div>
              <div style={{ fontSize: 12, marginTop: 4 }}>
                {apiError}. Check that the FastAPI server is running at <code>http://127.0.0.1:8000</code>.
              </div>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={fetchAllData}>
              Retry Connection
            </button>
          </div>
        )}

        {/* Top Real-Time Status Cards */}
        <div className="grid-3 mb-6" style={{ alignItems: 'stretch' }}>
          {/* Card 1: Live Motion Status */}
          <div className="card" style={{
            position: 'relative',
            borderColor: isMotionDetected ? 'var(--success)' : 'var(--border)',
            boxShadow: isMotionDetected ? '0 0 20px rgba(16, 185, 129, 0.2)' : 'none',
          }}>
            <div className="card-header" style={{ paddingBottom: 8 }}>
              <div className="card-title">
                <Activity size={16} /> Live Motion Status
              </div>
              <span className={`badge ${isMotionDetected ? 'badge-success' : 'badge-neutral'}`}>
                {isMotionDetected ? '● DETECTED' : '○ IDLE / CLEAR'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 8 }}>
              <div style={{
                width: 54, height: 54, borderRadius: 14,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 24,
                background: isMotionDetected ? 'rgba(16, 185, 129, 0.2)' : 'var(--bg-surface)',
                border: `2px solid ${isMotionDetected ? 'var(--success)' : 'var(--border)'}`,
                color: isMotionDetected ? 'var(--success)' : 'var(--text-muted)',
              }}>
                {isMotionDetected ? '🏃' : '🛌'}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 800, color: isMotionDetected ? 'var(--success)' : 'var(--text-secondary)' }}>
                  {isMotionDetected ? 'Motion Detected' : 'No Motion Detected'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  {latestMotionEvent ? (
                    <>
                      <span>{latestMotionEvent.sensor_id}</span>
                      {latestMotionEvent.location && (
                        <span> · <MapPin size={11} style={{ display: 'inline', verticalAlign: 'middle' }} /> {latestMotionEvent.location}</span>
                      )}
                    </>
                  ) : (
                    'No motion events logged yet'
                  )}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  <Clock size={11} style={{ display: 'inline', marginRight: 4 }} />
                  {formatRelativeTime(motionInfo?.seconds_since_last_motion)}
                </div>
              </div>
            </div>
            {latestMotionEvent?.raw_value !== null && latestMotionEvent?.raw_value !== undefined && (
              <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                <span>Raw Sensor Value:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--primary-light)' }}>
                  {latestMotionEvent.raw_value}
                </span>
              </div>
            )}
          </div>

          {/* Card 2: Physical Device Connection Diagnostics */}
          <div className="card">
            <div className="card-header" style={{ paddingBottom: 8 }}>
              <div className="card-title">
                <Radio size={16} /> Device Diagnostics
              </div>
              <span className={`badge ${
                isHardwareOnline ? 'badge-success' :
                hardwareConfigured ? 'badge-warning' : 'badge-neutral'
              }`}>
                {isHardwareOnline ? 'Hardware Online' :
                 hardwareConfigured ? 'Hardware Standby' : 'No Hardware'}
              </span>
            </div>
            <div style={{ marginTop: 8 }}>
              {isHardwareOnline ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <CheckCircle2 size={18} color="var(--success)" />
                    <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--success)' }}>
                      ESP32 / Controller Connected
                    </span>
                  </div>
                  {onlineDevices.map(d => (
                    <div key={d.device_id} style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>ID: {d.device_id}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        IP: {d.ip_address || '192.168.x.x'} · Ping: {d.seconds_since_last_seen}s ago
                        {d.battery_level !== null && ` · Battery: ${d.battery_level}%`}
                        {d.rssi !== null && ` · RSSI: ${d.rssi} dBm`}
                      </div>
                    </div>
                  ))}
                </div>
              ) : hardwareConfigured ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <AlertCircle size={18} color="var(--warning)" />
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--warning)' }}>
                      Device Offline (Awaiting Heartbeat)
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    Last seen {deviceStatus?.devices?.[0]?.seconds_since_last_seen}s ago. Check WiFi or power.
                  </div>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 6 }}>
                    No physical ESP32 connected yet.
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>
                    Using simulator & dataset events. Use <strong>Test Hardware Event</strong> to simulate physical hardware ingestion.
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Card 3: Stream Summary & Source Counts */}
          <div className="card">
            <div className="card-header" style={{ paddingBottom: 8 }}>
              <div className="card-title">
                <Gauge size={16} /> Ingestion Breakdown (1h)
              </div>
              <span className="badge badge-neutral">{total} Total Events</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
              {[
                { label: 'Hardware', count: liveStatus?.source_counts_last_hour?.hardware || 0, color: 'var(--success)', badge: 'badge-hardware' },
                { label: 'Simulator', count: liveStatus?.source_counts_last_hour?.simulator || 0, color: 'var(--demo)', badge: 'badge-demo' },
                { label: 'Dataset', count: liveStatus?.source_counts_last_hour?.dataset || 0, color: 'var(--accent-cyan)', badge: 'badge-cyan' },
                { label: 'REST API', count: liveStatus?.source_counts_last_hour?.api || 0, color: 'var(--info)', badge: 'badge-info' },
              ].map(item => (
                <div key={item.label} style={{
                  background: 'var(--bg-surface)', border: '1px solid var(--border)',
                  borderRadius: 8, padding: '8px 10px',
                }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: item.color }}>{item.count}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Filters and Simulator Bar */}
        <div className="card mb-4" style={{ padding: '12px 16px' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div className="filters-bar" style={{ margin: 0, padding: 0, border: 'none', background: 'transparent' }}>
              <Filter size={14} color="var(--text-muted)" />
              <label>Source:</label>
              <select value={filters.source} onChange={e => handleFilter('source', e.target.value)}>
                <option value="">All Sources</option>
                <option value="hardware">Physical Hardware Only</option>
                <option value="simulator">Simulator (Demo) Only</option>
                <option value="dataset">Dataset Import Only</option>
                <option value="api">REST API Only</option>
              </select>

              <label>Resident:</label>
              <select value={filters.resident_id} onChange={e => handleFilter('resident_id', e.target.value)}>
                <option value="">All Residents</option>
                <option value="R1">R1</option>
                <option value="R2">R2</option>
              </select>

              <label>Sensor ID:</label>
              <input
                placeholder="e.g. PIR_KITCHEN"
                value={filters.sensor_id}
                onChange={e => handleFilter('sensor_id', e.target.value)}
                style={{ maxWidth: 160 }}
              />
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-secondary btn-sm" onClick={handleSimulate}>
                <Cpu size={14} color="var(--demo)" /> Simulate Demo Batch
              </button>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginBottom: 12, fontSize: 12, color: 'var(--text-muted)' }}>
          <span><span style={{ borderLeft: '3px solid var(--success)', paddingLeft: 6, fontWeight: 600, color: 'var(--success)' }}>Physical Hardware</span> (source="hardware")</span>
          <span><span style={{ borderLeft: '3px solid var(--demo)', paddingLeft: 6, fontWeight: 600, color: 'var(--demo)' }}>Simulator Demo</span> (source="simulator")</span>
          <span><span style={{ borderLeft: '3px solid var(--accent-cyan)', paddingLeft: 6 }}>Dataset Upload</span> (source="dataset")</span>
          <span><span style={{ borderLeft: '3px solid var(--accent-emerald)', paddingLeft: 6 }}>REST API</span> (source="api")</span>
        </div>

        {/* Live Event Stream Table */}
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Sensor ID</th>
                <th>Location</th>
                <th>Type</th>
                <th>State</th>
                <th>Raw Value</th>
                <th>Resident</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: 36, color: 'var(--text-muted)' }}>
                    <div className="spinner" style={{ margin: '0 auto 10px' }} />
                    Loading real-time events…
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <div className="empty-state" style={{ padding: 40 }}>
                      <Wifi size={36} color="var(--text-muted)" />
                      <p style={{ marginTop: 10, fontSize: 14 }}>
                        {filters.source || filters.sensor_id || filters.resident_id
                          ? 'No sensor events match the selected filters.'
                          : 'No sensor events found in the database.'}
                      </p>
                      <div style={{ display: 'flex', gap: 10, justifyContent: 'center', marginTop: 12 }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => setFilters({ resident_id: '', sensor_id: '', source: '' })}>
                          Clear Filters
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={() => setShowTestModal(true)}>
                          Send Test Event
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                events.map(ev => {
                  const sourceConfig = SOURCE_LABELS[ev.source] || { label: ev.source, class: 'badge-neutral', icon: Wifi };
                  const SourceIcon = sourceConfig.icon;
                  return (
                    <tr key={ev.id} className={`event-row source-${ev.source}`} style={{ display: 'table-row', animation: 'none' }}>
                      <td className="event-timestamp">
                        {new Date(ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        <span style={{ display: 'block', fontSize: 10, opacity: 0.6 }}>
                          {new Date(ev.timestamp).toLocaleDateString()}
                        </span>
                      </td>
                      <td className="event-sensor-id">
                        {ev.sensor_id}
                      </td>
                      <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {ev.location ? (
                          <span><MapPin size={11} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />{ev.location}</span>
                        ) : (
                          <span style={{ opacity: 0.5 }}>—</span>
                        )}
                      </td>
                      <td>
                        <span className="badge badge-neutral" style={{ textTransform: 'capitalize' }}>
                          {ev.sensor_type}
                        </span>
                      </td>
                      <td>
                        <StateTag state={ev.sensor_state} />
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                        {ev.raw_value !== null && ev.raw_value !== undefined ? (
                          <span style={{ color: 'var(--primary-light)', fontWeight: 600 }}>{ev.raw_value}</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>—</span>
                        )}
                      </td>
                      <td style={{ fontWeight: 600 }}>
                        {ev.resident_id || '—'}
                      </td>
                      <td>
                        <span className={`badge ${sourceConfig.class}`}>
                          <SourceIcon size={11} /> {sourceConfig.label}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Known Sensor Registry */}
        {metadata.length > 0 && (
          <div className="card mt-6">
            <div className="card-header">
              <div className="card-title">
                <Wifi size={16} /> Known Sensor Registry ({metadata.length} sensors configured)
              </div>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              {metadata.map(s => (
                <div key={s.sensor_id} style={{
                  background: 'var(--bg-surface)', border: '1px solid var(--border)',
                  borderRadius: 8, padding: '8px 12px', fontSize: 11, minWidth: 160,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--primary-light)', fontFamily: 'var(--font-mono)' }}>
                      {s.sensor_id}
                    </span>
                    {s.dataset_source === 'hardware' && (
                      <span className="badge badge-hardware" style={{ fontSize: 9, padding: '1px 5px' }}>HW</span>
                    )}
                  </div>
                  <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
                    {s.sensor_type} · {s.location || 'Unassigned'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Quick Test Hardware Event Modal */}
      {showTestModal && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10000,
        }}>
          <div className="card" style={{ maxWidth: 540, width: '92%', padding: 24, boxShadow: 'var(--shadow-lg)' }}>
            <div className="card-header" style={{ padding: 0, marginBottom: 16 }}>
              <div className="card-title" style={{ fontSize: 16 }}>
                <Radio size={18} color="var(--success)" /> Ingest Physical Sensor Test Event
              </div>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => { setShowTestModal(false); setTestResult(null); }}
              >
                ✕
              </button>
            </div>

            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
              Simulates a physical IoT node event via the secure development test pipeline. <code>DEVICE_API_KEY</code> is validated server-side without exposure to the browser.
            </p>

            {testResult ? (
              <div>
                <div style={{
                  background: testResult.status === 'duplicate_ignored' ? 'rgba(234, 179, 8, 0.12)' : 'rgba(34, 197, 94, 0.12)',
                  border: `1px solid ${testResult.status === 'duplicate_ignored' ? 'rgba(234, 179, 8, 0.4)' : 'rgba(34, 197, 94, 0.4)'}`,
                  borderRadius: 8,
                  padding: '12px 16px',
                  marginBottom: 16,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Radio size={20} color={testResult.status === 'duplicate_ignored' ? '#eab308' : '#22c55e'} />
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13, color: testResult.status === 'duplicate_ignored' ? '#eab308' : '#22c55e' }}>
                        {testResult.status === 'duplicate_ignored' ? 'Duplicate Event Ignored (Debounced)' : 'Physical Event Ingested Successfully'}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {testResult.message || testResult.note || 'Persisted to active database backend'}
                      </div>
                    </div>
                  </div>
                  <span className={`badge ${testResult.status === 'duplicate_ignored' ? 'badge-demo' : 'badge-hardware'}`} style={{ textTransform: 'uppercase', fontSize: 11 }}>
                    {testResult.status}
                  </span>
                </div>

                {/* Realistic event attributes grid */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, 1fr)',
                  gap: 10,
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: 14,
                  fontSize: 12,
                  marginBottom: 16
                }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Database Event ID</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>#{testResult.id || 'N/A'}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Sensor Identifier</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--primary-light)' }}>{testResult.sensor_id}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Sensor State</span>
                    <span><StateTag state={testResult.sensor_state} /></span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Hardware Device Node</span>
                    <span style={{ fontFamily: 'var(--font-mono)' }}>{testResult.device_node_id || testResult.device_id || 'N/A'}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Location</span>
                    <span>{testResult.location || 'Unassigned'}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Resident ID</span>
                    <span>{testResult.resident_id || 'R1'}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Raw Value</span>
                    <span>{testResult.raw_value !== null && testResult.raw_value !== undefined ? testResult.raw_value : '—'}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Debounce State</span>
                    <span style={{ color: testResult.debounced ? 'var(--warning)' : 'var(--success)' }}>
                      {testResult.debounced ? '⚡ Suppressed (< 0.5s)' : '✅ Accepted & Written'}
                    </span>
                  </div>
                  <div style={{ gridColumn: 'span 2' }}>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Authentication Mode</span>
                    <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                      🔒 Server-side verified (mode: <code>{testResult.auth}</code>) — <code>DEVICE_API_KEY</code> applied server-side
                    </span>
                  </div>
                  <div style={{ gridColumn: 'span 2' }}>
                    <span style={{ color: 'var(--text-muted)', display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>Timestamp</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{testResult.timestamp || new Date().toISOString()}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setTestResult(null)}
                  >
                    Send Another Event
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => { setShowTestModal(false); setTestResult(null); }}
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSendTestHardwareEvent}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Sensor ID</label>
                    <input
                      value={testPayload.sensor_id}
                      onChange={e => setTestPayload({ ...testPayload, sensor_id: e.target.value.toUpperCase() })}
                      placeholder="e.g. PIR_LIVING"
                      required
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Sensor Type</label>
                    <select
                      value={testPayload.sensor_type}
                      onChange={e => setTestPayload({ ...testPayload, sensor_type: e.target.value })}
                      style={{ width: '100%' }}
                    >
                      <option value="motion">motion (PIR)</option>
                      <option value="door">door (contact)</option>
                      <option value="temperature">temperature</option>
                      <option value="appliance">appliance</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Sensor State</label>
                    <select
                      value={testPayload.sensor_state}
                      onChange={e => setTestPayload({ ...testPayload, sensor_state: e.target.value })}
                      style={{ width: '100%' }}
                    >
                      <option value="ON">ON (Detected)</option>
                      <option value="OFF">OFF (Clear)</option>
                      <option value="OPEN">OPEN</option>
                      <option value="CLOSED">CLOSED</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Device Node ID</label>
                    <input
                      value={testPayload.device_id}
                      onChange={e => setTestPayload({ ...testPayload, device_id: e.target.value })}
                      placeholder="esp32-node-01"
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Raw Sensor Value (optional)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={testPayload.raw_value}
                      onChange={e => setTestPayload({ ...testPayload, raw_value: parseFloat(e.target.value) || 0 })}
                      placeholder="1.0"
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Resident ID</label>
                    <select
                      value={testPayload.resident_id}
                      onChange={e => setTestPayload({ ...testPayload, resident_id: e.target.value })}
                      style={{ width: '100%' }}
                    >
                      <option value="R1">R1</option>
                      <option value="R2">R2</option>
                    </select>
                  </div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => { setShowTestModal(false); setTestResult(null); }}
                  >
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary btn-sm" disabled={submittingTest}>
                    {submittingTest ? 'Ingesting…' : 'Send Hardware Event'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
