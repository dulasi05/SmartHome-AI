import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Activity, BookOpen, AlertTriangle,
  Database, Layers, Menu, X, Home, Wifi, BrainCircuit,
  ShieldAlert, FlaskConical, Sun, Moon, Settings, ChevronDown, ChevronRight,
  Wrench
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

// Primary Resident-Facing Navigation
const RESIDENT_NAV_ITEMS = [
  { path: '/', label: 'Home Dashboard', icon: LayoutDashboard },
  { path: '/sensors', label: 'Live Sensors', icon: Wifi },
  { path: '/recognition', label: 'Activity History', icon: Activity },
  { path: '/routine', label: 'Daily Routine', icon: BookOpen },
  { path: '/alerts', label: 'Alerts & Notices', icon: ShieldAlert, showBadge: true },
  { path: '/settings', label: 'Settings', icon: Settings },
];

// Developer, Admin & Technical Architecture Tools
const DEVELOPER_NAV_ITEMS = [
  { path: '/architecture', label: 'System Architecture', icon: Layers },
  { path: '/datasets', label: 'Dataset Management', icon: Database },
  { path: '/training', label: 'Model Training', icon: BrainCircuit },
  { path: '/explain', label: 'AI Explainability', icon: FlaskConical },
  { path: '/anomalies', label: 'Anomaly Diagnostics', icon: AlertTriangle },
];

const RESIDENT_SYSTEM_STATUS = [
  { label: 'Sensor Network', status: 'connected', display: 'ACTIVE' },
  { label: 'Activity AI Engine', status: 'ready', display: 'READY' },
  { label: 'MySQL Storage', status: 'connected', display: 'CONNECTED' },
];

export default function Sidebar({ alertCount = 0 }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme, toggleTheme, isDark } = useTheme();

  // If user is currently on an advanced/dev route, expand developer section automatically
  const isDevRoute = DEVELOPER_NAV_ITEMS.some(item => location.pathname === item.path);
  const [devToolsOpen, setDevToolsOpen] = useState(isDevRoute);

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
          <h1>SmartHome AI</h1>
          <p>Resident Activity Monitor</p>
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav">
          <div className="nav-section-label">Home Monitoring</div>
          {RESIDENT_NAV_ITEMS.map(({ path, label, icon: Icon, showBadge }) => {
            const isActive = location.pathname === path || (path === '/recognition' && location.pathname === '/history');
            return (
              <button
                key={path}
                className={`nav-item${isActive ? ' active' : ''}`}
                onClick={() => handleNav(path)}
                style={{ width: '100%', background: 'none', textAlign: 'left' }}
              >
                <Icon size={16} />
                <span>{label}</span>
                {showBadge && alertCount > 0 && (
                  <span className="nav-badge">{alertCount}</span>
                )}
              </button>
            );
          })}

          {/* Collapsible Developer & Technical Section */}
          <div style={{ marginTop: '1.25rem' }}>
            <button
              type="button"
              onClick={() => setDevToolsOpen(o => !o)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.4rem 0.6rem',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                fontSize: '0.72rem',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                cursor: 'pointer',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Wrench size={13} />
                Developer Tools
              </span>
              {devToolsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>

            {devToolsOpen && (
              <div style={{ paddingLeft: '0.25rem', marginTop: '0.35rem', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                {DEVELOPER_NAV_ITEMS.map(({ path, label, icon: Icon }) => (
                  <button
                    key={path}
                    className={`nav-item${location.pathname === path ? ' active' : ''}`}
                    onClick={() => handleNav(path)}
                    style={{ 
                      width: '100%', 
                      background: 'none', 
                      textAlign: 'left',
                      fontSize: '0.82rem',
                      padding: '0.45rem 0.65rem'
                    }}
                  >
                    <Icon size={15} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </nav>

        {/* Footer status & theme */}
        <div className="sidebar-footer">
          {/* Theme Switcher Button */}
          <div className="theme-toggle-container">
            <button
              type="button"
              className="theme-toggle-btn"
              onClick={toggleTheme}
              title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
              aria-label="Toggle light and dark theme"
            >
              <div className="theme-toggle-icon">
                {isDark ? <Sun size={15} /> : <Moon size={15} />}
              </div>
              <span className="theme-toggle-text">
                {isDark ? 'Light Mode' : 'Dark Mode'}
              </span>
              <div className={`theme-toggle-track ${theme}`}>
                <div className="theme-toggle-thumb" />
              </div>
            </button>
          </div>

          <div className="system-status-mini">
            <h4>System Health</h4>
            {RESIDENT_SYSTEM_STATUS.map(({ label, status, display }) => (
              <div key={label} className="status-dot-row">
                <div className={`status-dot ${status}`} />
                <span>{label}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10, opacity: 0.75, fontWeight: 500 }}>
                  {display}
                </span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </>
  );
}
