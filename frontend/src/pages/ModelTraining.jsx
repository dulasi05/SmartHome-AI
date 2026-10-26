/**
 * Model Training Page — Phase 2
 * Configure and run the Powerformer model training with live progress.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  BrainCircuit, Play, RefreshCw, CheckCircle2, AlertTriangle,
  Settings, Cpu, TrendingUp, Database
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { startTraining, getTrainingStatus, getCalibrationStatus } from '../services/api';
import { useToast } from '../hooks/useToast';

const STATUS_COLORS = {
  idle: 'var(--text-muted)',
  running: 'var(--warning)',
  done: 'var(--success)',
  error: 'var(--error)',
};

const STATUS_ICONS = {
  idle: <Settings size={14} />,
  running: <div className="spinner" style={{ width: 14, height: 14 }} />,
  done: <CheckCircle2 size={14} />,
  error: <AlertTriangle size={14} />,
};

export default function ModelTraining() {
  const { addToast } = useToast();
  const [status, setStatus] = useState(null);
  const [calStatus, setCalStatus] = useState(null);
  const [polling, setPolling] = useState(false);
  const [config, setConfig] = useState({
    n_epochs: 10,
    window_size: 30,
    stride: 10,
    d_model: 64,
    n_heads: 4,
    n_layers: 2,
    lr: 0.001,
    batch_size: 32,
    alpha: 1.0,
    dropout: 0.1,
    seed: 42,
    use_synthetic: true,
  });

  const fetchStatus = useCallback(async () => {
    try {
      const [s, cal] = await Promise.all([getTrainingStatus(), getCalibrationStatus()]);
      setStatus(s);
      setCalStatus(cal);
    } catch (e) { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(async () => {
      await fetchStatus();
      const s = await getTrainingStatus();
      if (s.status !== 'running') {
        setPolling(false);
        if (s.status === 'done') addToast('✅ Training complete!', 'success');
        if (s.status === 'error') addToast(`❌ Training failed: ${s.error_message}`, 'error');
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, fetchStatus, addToast]);

  const handleTrain = async () => {
    try {
      await startTraining(config);
      setPolling(true);
      addToast('🚀 Training started in background...', 'info');
      fetchStatus();
    } catch (e) {
      addToast(`Failed to start training: ${e.response?.data?.detail || e.message}`, 'error');
    }
  };

  const chartData = status?.train_loss?.map((tl, i) => ({
    epoch: i + 1,
    train_loss: tl,
    val_loss: status.val_loss?.[i] ?? null,
    val_acc: status.val_acc?.[i] ? (status.val_acc[i] * 100).toFixed(1) : null,
  })) || [];

  const isRunning = status?.status === 'running';
  const isDone = status?.status === 'done';

  return (
    <div>
      <div className="page-header">
        <div className="page-header-inner">
          <div>
            <h2>Model Training &amp; Evaluation</h2>
            <p>Configure and train the Powerformer-style activity recognition model</p>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={fetchStatus}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <div className="page-body">
        {/* Status Bar */}
        <div className="card mb-6" style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: STATUS_COLORS[status?.status || 'idle'] }}>
                {STATUS_ICONS[status?.status || 'idle']}
              </span>
              <span style={{ fontWeight: 700, textTransform: 'capitalize', color: STATUS_COLORS[status?.status || 'idle'] }}>
                {status?.status || 'idle'}
              </span>
            </div>
            {isRunning && (
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span className="text-sm text-muted">Epoch {status.epoch} / {status.total_epochs}</span>
                  <span className="text-sm text-muted">{Math.round(status.progress * 100)}%</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${status.progress * 100}%` }} />
                </div>
              </div>
            )}
            {isDone && (
              <span style={{ color: 'var(--success)', fontSize: 13 }}>
                Best Val Acc: <strong>{status.val_acc?.length ? (Math.max(...status.val_acc) * 100).toFixed(1) + '%' : 'N/A'}</strong>
              </span>
            )}
            {calStatus?.fitted && (
              <span className="badge badge-success">Calibrated (T={calStatus.temperature?.toFixed(3)})</span>
            )}
          </div>
          {status?.error_message && (
            <div className="demo-banner" style={{ marginTop: 12, background: 'rgba(239,68,68,0.08)', borderColor: 'var(--error)' }}>
              <AlertTriangle size={14} /> {status.error_message}
            </div>
          )}
        </div>

        <div className="grid-2 mb-6">
          {/* Config */}
          <div className="card">
            <div className="card-header">
              <div className="card-title"><Settings size={16} /> Training Configuration</div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {[
                { key: 'n_epochs', label: 'Epochs', type: 'number', min: 1, max: 100 },
                { key: 'window_size', label: 'Window Size', type: 'number', min: 5, max: 200 },
                { key: 'stride', label: 'Stride', type: 'number', min: 1, max: 100 },
                { key: 'd_model', label: 'd_model', type: 'number', min: 16, max: 512 },
                { key: 'n_heads', label: 'Attn Heads', type: 'number', min: 1, max: 16 },
                { key: 'n_layers', label: 'Layers', type: 'number', min: 1, max: 8 },
                { key: 'lr', label: 'Learning Rate', type: 'number', step: 0.0001 },
                { key: 'batch_size', label: 'Batch Size', type: 'number', min: 4, max: 256 },
                { key: 'alpha', label: 'Decay Alpha (α)', type: 'number', step: 0.1 },
                { key: 'dropout', label: 'Dropout', type: 'number', step: 0.05, min: 0, max: 0.5 },
                { key: 'seed', label: 'Random Seed', type: 'number' },
              ].map(({ key, label, ...inputProps }) => (
                <div key={key}>
                  <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    {label}
                  </label>
                  <input
                    type={inputProps.type}
                    className="input"
                    value={config[key]}
                    step={inputProps.step || 1}
                    min={inputProps.min}
                    max={inputProps.max}
                    onChange={e => setConfig(c => ({ ...c, [key]: parseFloat(e.target.value) || e.target.value }))}
                    disabled={isRunning}
                    style={{ width: '100%', padding: '6px 10px', fontSize: 13 }}
                  />
                </div>
              ))}
            </div>

            <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="checkbox"
                id="use_synthetic"
                checked={config.use_synthetic}
                onChange={e => setConfig(c => ({ ...c, use_synthetic: e.target.checked }))}
                disabled={isRunning}
              />
              <label htmlFor="use_synthetic" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Use synthetic data if real dataset insufficient
              </label>
            </div>

            <button
              className="btn btn-primary"
              style={{ width: '100%', marginTop: 16 }}
              onClick={handleTrain}
              disabled={isRunning}
            >
              {isRunning
                ? <><div className="spinner" style={{ width: 14, height: 14 }} /> Training…</>
                : <><Play size={14} /> Start Training</>
              }
            </button>

            <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              <strong>Model:</strong> Powerformer-style (WCMHA temporal decay)<br />
              <strong>Calibration:</strong> Temperature scaling (val set only)<br />
              <strong>Routine:</strong> JSD baseline after training<br />
              <strong>IF:</strong> Isolation Forest on daily features
            </div>
          </div>

          {/* Architecture info */}
          <div className="card">
            <div className="card-header">
              <div className="card-title"><BrainCircuit size={16} /> Model Architecture</div>
              <span className="badge badge-info">Powerformer-Style</span>
            </div>

            <div className="demo-banner" style={{ marginBottom: 16 }}>
              <AlertTriangle size={14} />
              This is a <strong>Powerformer-inspired</strong> implementation. WCMHA temporal decay is
              implemented as power-law biases on attention logits. Not a verbatim reproduction of
              any published Powerformer paper.
            </div>

            {[
              { label: 'Input', desc: 'One-hot sensor IDs + states + time-of-day sin/cos features' },
              { label: 'Embedding', desc: 'Linear projection → LayerNorm → GELU → d_model dimensions' },
              { label: 'Pos. Encoding', desc: 'Learnable positional embedding (max 512 positions)' },
              { label: 'WCMHA', desc: 'Power-law temporal decay: w_ij = (1 + |t_i - t_j| / scale)^{-α}' },
              { label: 'Transformer', desc: 'N × [WCMHA + LayerNorm + FFN + LayerNorm] (pre-norm)' },
              { label: 'Aggregation', desc: 'Mean pooling across sequence dimension' },
              { label: 'Output', desc: 'Separate classification head per resident → n_activities logits' },
            ].map(({ label, desc }) => (
              <div key={label} style={{
                display: 'flex', gap: 10, padding: '8px 0',
                borderBottom: '1px solid var(--border)',
              }}>
                <span style={{
                  background: 'linear-gradient(135deg, var(--primary), var(--accent-purple))',
                  borderRadius: 6, padding: '2px 8px',
                  fontSize: 10, fontWeight: 700, color: '#fff', flexShrink: 0,
                  alignSelf: 'flex-start', marginTop: 2,
                }}>{label}</span>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{desc}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Training curves */}
        {chartData.length > 0 && (
          <div className="card mb-6">
            <div className="card-header">
              <div className="card-title"><TrendingUp size={16} /> Training Curves</div>
              {isDone && <span className="badge badge-success">Training Complete</span>}
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="epoch" stroke="var(--text-muted)" tick={{ fontSize: 11 }} label={{ value: 'Epoch', position: 'insideBottom', offset: -4, fill: 'var(--text-muted)', fontSize: 11 }} />
                <YAxis stroke="var(--text-muted)" tick={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                <Legend />
                <Line type="monotone" dataKey="train_loss" stroke="var(--primary)" strokeWidth={2} dot={false} name="Train Loss" />
                <Line type="monotone" dataKey="val_loss" stroke="var(--warning)" strokeWidth={2} dot={false} name="Val Loss" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Val Accuracy */}
        {chartData.length > 0 && chartData.some(d => d.val_acc !== null) && (
          <div className="card">
            <div className="card-header">
              <div className="card-title"><Cpu size={16} /> Validation Accuracy</div>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="epoch" stroke="var(--text-muted)" tick={{ fontSize: 11 }} />
                <YAxis stroke="var(--text-muted)" tick={{ fontSize: 11 }} domain={[0, 100]} />
                <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} formatter={v => [`${v}%`, 'Val Acc']} />
                <Line type="monotone" dataKey="val_acc" stroke="var(--success)" strokeWidth={2} dot={false} name="Val Acc (%)" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
