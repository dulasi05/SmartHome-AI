/**
 * Dataset Management Page
 * Upload ARAS/CASAS datasets, preview records, and view preprocessing results.
 */
import { useState, useEffect, useRef } from 'react';
import { Database, Upload, RefreshCw, CheckCircle, XCircle, Eye } from 'lucide-react';
import { listDatasetUploads, uploadDataset, getDatasetPreview } from '../services/api';
import { useToast } from '../hooks/useToast';

const STATUS_BADGE = {
  done: 'badge-success',
  processing: 'badge-info',
  error: 'badge-error',
  pending: 'badge-neutral',
};

export default function DatasetManagement() {
  const { addToast } = useToast();
  const [uploads, setUploads] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewId, setPreviewId] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [datasetType, setDatasetType] = useState('auto');
  const [lastResult, setLastResult] = useState(null);
  const fileInputRef = useRef(null);

  const fetchUploads = async () => {
    try {
      const data = await listDatasetUploads();
      setUploads(data.uploads || []);
    } catch { addToast('Failed to load uploads', 'error'); }
  };

  useEffect(() => { fetchUploads(); }, []);

  const handleUpload = async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      addToast('Only CSV files are supported.', 'error'); return;
    }
    setUploading(true);
    setLastResult(null);
    try {
      const result = await uploadDataset(file, datasetType);
      setLastResult(result);
      addToast(`✅ Uploaded ${result.filename} — ${result.stats?.cleaned_count || 0} records`, 'success');
      await fetchUploads();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'object' ? (detail?.message || JSON.stringify(detail)) : detail || err.message;
      addToast(`Upload failed: ${msg}`, 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleFileInput = (e) => {
    handleUpload(e.target.files[0]);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    handleUpload(e.dataTransfer.files[0]);
  };

  const handlePreview = async (uploadId) => {
    if (previewId === uploadId) { setPreviewId(null); setPreviewData(null); return; }
    try {
      const data = await getDatasetPreview(uploadId, 30);
      setPreviewData(data);
      setPreviewId(uploadId);
    } catch { addToast('Failed to load preview', 'error'); }
  };

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Dataset Management</h2>
            <p>Upload ARAS/CASAS CSV datasets — Layer 1 & 2: Data + Processing</p>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={fetchUploads}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <div className="page-body">
        <div className="grid-2-1">
          {/* Upload zone + results */}
          <div>
            {/* Upload area */}
            <div className="card mb-4">
              <div className="card-header">
                <div className="card-title"><Upload size={16} /> Upload Dataset</div>
                <select value={datasetType} onChange={e => setDatasetType(e.target.value)} style={{ fontSize: 12 }}>
                  <option value="auto">Auto-detect</option>
                  <option value="ARAS">ARAS</option>
                  <option value="CASAS">CASAS</option>
                  <option value="custom">Custom</option>
                </select>
              </div>

              <div
                className={`upload-zone${dragActive ? ' drag-active' : ''}`}
                onDragOver={e => { e.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                {uploading ? (
                  <>
                    <div className="spinner" style={{ margin: '0 auto 16px' }} />
                    <h3>Processing…</h3>
                    <p>Cleaning, encoding, generating windows…</p>
                  </>
                ) : (
                  <>
                    <div className="upload-zone-icon">📂</div>
                    <h3>Drop CSV file or click to browse</h3>
                    <p>Supports ARAS, CASAS, and custom CSV formats · Max 50 MB</p>
                  </>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv"
                  style={{ display: 'none' }}
                  onChange={handleFileInput}
                />
              </div>
            </div>

            {/* Preprocessing results */}
            {lastResult && (
              <div className="card mb-4">
                <div className="card-header">
                  <div className="card-title"><CheckCircle size={16} color="var(--success)" /> Preprocessing Results</div>
                  <span className="badge badge-success">Done</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                  {[
                    { label: 'Raw Records', value: lastResult.stats?.raw_count },
                    { label: 'Cleaned', value: lastResult.stats?.cleaned_count },
                    { label: 'Duplicates Removed', value: lastResult.stats?.duplicate_count },
                    { label: 'Invalid Removed', value: lastResult.stats?.invalid_count },
                    { label: 'Sliding Windows', value: lastResult.stats?.window_count },
                    { label: 'Dataset Type', value: lastResult.dataset_type },
                  ].map(s => (
                    <div key={s.label} style={{
                      background: 'var(--bg-surface)', borderRadius: 8, padding: '8px 12px',
                    }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{s.label}</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--primary-light)' }}>{s.value ?? '—'}</div>
                    </div>
                  ))}
                </div>

                {lastResult.stats?.sensors?.length > 0 && (
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
                      Detected Sensors ({lastResult.stats.sensors.length}):
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                      {lastResult.stats.sensors.map(s => (
                        <span key={s} style={{
                          fontFamily: 'var(--font-mono)', fontSize: 11,
                          background: 'var(--bg-card)', border: '1px solid var(--border)',
                          borderRadius: 4, padding: '2px 8px', color: 'var(--primary-light)',
                        }}>{s}</span>
                      ))}
                    </div>
                  </div>
                )}

                {lastResult.stats?.activities?.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Activities:</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                      {lastResult.stats.activities.map(a => (
                        <span key={a} className="badge badge-neutral" style={{ textTransform: 'capitalize' }}>
                          {a.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {lastResult.stats?.errors?.length > 0 && (
                  <div style={{ marginTop: 10, color: 'var(--error)', fontSize: 12 }}>
                    ⚠️ Errors: {lastResult.stats.errors.join('; ')}
                  </div>
                )}
              </div>
            )}

            {/* Preview table */}
            {previewData && (
              <div className="card mb-4">
                <div className="card-header">
                  <div className="card-title"><Eye size={16} /> Preview: {previewData.filename}</div>
                  <button className="btn btn-ghost btn-sm" onClick={() => { setPreviewId(null); setPreviewData(null); }}>
                    ✕
                  </button>
                </div>
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
                      </tr>
                    </thead>
                    <tbody>
                      {previewData.events?.map((ev, i) => (
                        <tr key={i}>
                          <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                            {new Date(ev.timestamp).toLocaleString()}
                          </td>
                          <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary-light)' }}>{ev.sensor_id}</td>
                          <td><span className="badge badge-neutral">{ev.sensor_type}</span></td>
                          <td style={{ fontWeight: 600 }}>{ev.sensor_state}</td>
                          <td>{ev.resident_id || '—'}</td>
                          <td style={{ fontSize: 12, textTransform: 'capitalize' }}>
                            {ev.activity_label?.replace(/_/g, ' ') || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Upload history */}
          <div className="card" style={{ alignSelf: 'flex-start' }}>
            <div className="card-header">
              <div className="card-title"><Database size={16} /> Upload History</div>
              <span className="badge badge-neutral">{uploads.length}</span>
            </div>
            {uploads.length === 0 ? (
              <div className="empty-state"><p>No datasets uploaded yet</p></div>
            ) : (
              uploads.map(u => (
                <div key={u.id} style={{
                  background: 'var(--bg-surface)', borderRadius: 8, padding: 12, marginBottom: 10,
                  border: '1px solid var(--border)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {u.filename}
                    </div>
                    <span className={`badge ${STATUS_BADGE[u.status] || 'badge-neutral'}`}>{u.status}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                    {u.dataset_type} · {new Date(u.upload_timestamp).toLocaleDateString()}
                    {u.record_count != null && ` · ${u.record_count} records`}
                  </div>
                  {u.error_message && (
                    <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 6 }}>⚠️ {u.error_message}</div>
                  )}
                  {u.status === 'done' && (
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => handlePreview(u.id)}
                    >
                      <Eye size={13} /> {previewId === u.id ? 'Hide Preview' : 'Preview Records'}
                    </button>
                  )}
                </div>
              ))
            )}

            {/* Format guide */}
            <div className="divider" />
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <strong style={{ color: 'var(--text-secondary)' }}>Supported formats:</strong>
              <ul style={{ marginTop: 6, paddingLeft: 16, lineHeight: 2 }}>
                <li><strong>ARAS:</strong> timestamp, sensor_id, sensor_state, resident_id, activity_label</li>
                <li><strong>CASAS:</strong> date, time, sensor_id, message, activity</li>
                <li><strong>Custom:</strong> any CSV with timestamp + sensor_id + sensor_state columns</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
