import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Activity, Cpu, BookOpen, AlertTriangle,
  Database, Layers, Menu, X, Home, Wifi, BrainCircuit,
  ShieldAlert, FlaskConical
} from 'lucide-react';

const NAV_ITEMS_PHASE1 = [
  { path: '/', label: 'Overview', icon: LayoutDashboard },
  { path: '/sensors', label: 'Live Sensors', icon: Wifi },
  { path: '/recognition', label: 'Activity Recognition', icon: Activity },
  { path: '/routine', label: 'Routine Analysis', icon: BookOpen },
  { path: '/anomalies', label: 'Anomaly Detection', icon: AlertTriangle },
  { path: '/datasets', label: 'Dataset Management', icon: Database },
  { path: '/architecture', label: 'System Architecture', icon: Layers },
];

const NAV_ITEMS_PHASE2 = [
  { path: '/training', label: 'Model Training', icon: BrainCircuit },
  { path: '/alerts', label: 'Alert Centre', icon: ShieldAlert, showBadge: true },
  { path: '/explain', label: 'Explainability', icon: FlaskConical },
];


const LAYER_STATUS = [
  { label: 'Data Layer', status: 'connected' },
  { label: 'Processing', status: 'ready' },
  { label: 'Intelligence', status: 'demo' },
  { label: 'Storage', status: 'connected' },
  { label: 'Presentation', status: 'running' },
];

export default function Sidebar({ alertCount = 0 }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleNav = (path) => {
    navigate(path);
    setMobileOpen(false);
  };

  return (
    <>
      {/* Mobile toggle */}
      <button
        className="mobile-nav-toggle btn"
        onClick={() => setMobileOpen(o => !o)}
        aria-label="Toggle navigation"
      >
        {mobileOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Backdrop */}
      {mobileOpen && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            zIndex: 99,
          }}
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside className={`sidebar${mobileOpen ? ' open' : ''}`}>
        {/* Logo */}
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">
            <Home size={20} color="white" />
          </div>
          <h1>SmartHome AR</h1>
          <p>Activity Recognition System</p>
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav">
          <div className="nav-section-label">Phase 1</div>
          {NAV_ITEMS_PHASE1.map(({ path, label, icon: Icon }) => (
            <button
              key={path}
              className={`nav-item${location.pathname === path ? ' active' : ''}`}
              onClick={() => handleNav(path)}
              style={{ width: '100%', background: 'none', textAlign: 'left' }}
            >
              <Icon size={16} />
              <span>{label}</span>
              {label === 'Anomaly Detection' && alertCount > 0 && (
                <span className="nav-badge">{alertCount}</span>
              )}
            </button>
          ))}

          <div className="nav-section-label" style={{ marginTop: 12 }}>Phase 2 — AI Research</div>
          {NAV_ITEMS_PHASE2.map(({ path, label, icon: Icon, showBadge }) => (
            <button
              key={path}
              className={`nav-item${location.pathname === path ? ' active' : ''}`}
              onClick={() => handleNav(path)}
              style={{ width: '100%', background: 'none', textAlign: 'left' }}
            >
              <Icon size={16} />
              <span>{label}</span>
              {showBadge && alertCount > 0 && (
                <span className="nav-badge">{alertCount}</span>
              )}
            </button>
          ))}
        </nav>


        {/* Layer status footer */}
        <div className="sidebar-footer">
          <div className="system-status-mini">
            <h4>Layer Status</h4>
            {LAYER_STATUS.map(({ label, status }) => (
              <div key={label} className="status-dot-row">
                <div className={`status-dot ${status}`} />
                <span>{label}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10, opacity: 0.7 }}>
                  {status === 'demo' ? 'DEMO' : status.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </>
  );
}
