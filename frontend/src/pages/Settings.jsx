import { useState, useEffect } from 'react';
import { 
  Settings as SettingsIcon, User, Moon, Sun, Cpu, Database, 
  Bell, CheckCircle2, AlertCircle, RefreshCw, Smartphone, ShieldCheck
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { checkHealth, getDeviceStatus } from '../services/api';
import { useToast } from '../hooks/useToast';

export default function Settings() {
  const { theme, toggleTheme, isDark } = useTheme();
  const { showSuccess, showError } = useToast();

  // Resident Profile
  const [residentId, setResidentId] = useState(
    () => localStorage.getItem('smartHome_residentId') || 'R1'
  );
  const [residentName, setResidentName] = useState(
    () => localStorage.getItem('smartHome_residentName') || (residentId === 'R1' ? 'Resident 1 (Main)' : 'Resident 2 (Guest/Family)')
  );

  // Notification Preferences (saved in localStorage)
  const [notifyUrgent, setNotifyUrgent] = useState(
    () => localStorage.getItem('pref_notify_urgent') !== 'false'
  );
  const [notifyRoutine, setNotifyRoutine] = useState(
    () => localStorage.getItem('pref_notify_routine') !== 'false'
  );
  const [quietHours, setQuietHours] = useState(
    () => localStorage.getItem('pref_quiet_hours') === 'true'
  );

  // Backend Health & Hardware Devices
  const [health, setHealth] = useState(null);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchSystemData = async () => {
    try {
      const [hData, dData] = await Promise.allSettled([
        checkHealth(),
        getDeviceStatus()
      ]);
      if (hData.status === 'fulfilled') {
        setHealth(hData.value);
      }
      if (dData.status === 'fulfilled') {
        setDevices(dData.value?.devices || []);
      }
    } catch (err) {
      console.error('Error fetching settings status:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchSystemData();
  }, []);

  const handleSaveProfile = (e) => {
    e.preventDefault();
    localStorage.setItem('smartHome_residentId', residentId);
    localStorage.setItem('smartHome_residentName', residentName);
    showSuccess(`Profile settings updated for ${residentName} (${residentId})`);
  };

  const handleTogglePref = (key, val, setter) => {
    setter(val);
    localStorage.setItem(key, String(val));
    showSuccess('Notification preference saved');
  };

  const handleRefresh = () => {
    setRefreshing(true);
    fetchSystemData();
  };

  return (
    <div className="page-container">
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <SettingsIcon size={26} color="var(--primary)" />
            Home & App Settings
          </h1>
          <p className="page-subtitle">
            Manage your resident profile, theme appearance, notifications, and connected IoT home hardware.
          </p>
        </div>
        <button 
          className="btn btn-secondary" 
          onClick={handleRefresh} 
          disabled={refreshing}
          style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}
        >
          <RefreshCw size={15} className={refreshing ? 'spin' : ''} />
          Refresh Status
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.25rem', marginTop: '1rem' }}>
        
        {/* Resident Profile Section */}
        <div className="card">
          <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <User size={18} color="var(--primary)" />
            <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600 }}>Resident Profile</h3>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
            Choose the active resident identity used for activity logging and daily routine analysis.
          </p>
          <form onSubmit={handleSaveProfile} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Resident Identifier
              </label>
              <select 
                className="input" 
                value={residentId} 
                onChange={(e) => {
                  const newId = e.target.value;
                  setResidentId(newId);
                  setResidentName(newId === 'R1' ? 'Resident 1 (Main)' : 'Resident 2 (Guest/Family)');
                }}
                style={{ width: '100%', padding: '0.55rem', borderRadius: '6px' }}
              >
                <option value="R1">Resident 1 (Primary Household Member - R1)</option>
                <option value="R2">Resident 2 (Secondary / Guest Member - R2)</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Display Name
              </label>
              <input 
                type="text" 
                className="input" 
                value={residentName} 
                onChange={(e) => setResidentName(e.target.value)}
                placeholder="e.g. Grandma, John, Primary Resident"
                style={{ width: '100%', padding: '0.55rem', borderRadius: '6px' }}
              />
            </div>
            <button type="submit" className="btn btn-primary" style={{ alignSelf: 'flex-start' }}>
              Save Profile
            </button>
          </form>
        </div>

        {/* Display & Appearance */}
        <div className="card">
          <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {isDark ? <Moon size={18} color="var(--primary)" /> : <Sun size={18} color="var(--primary)" />}
            <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600 }}>Display & Appearance</h3>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
            Personalize your viewing experience. Select between high-contrast dark mode or clean daylight view.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.85rem 1rem', background: 'var(--bg-elevated)', borderRadius: '8px' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>Theme Mode</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Currently active: <strong>{isDark ? 'Dark Theme' : 'Light Theme'}</strong>
              </div>
            </div>
            <button 
              type="button" 
              className="btn btn-secondary" 
              onClick={toggleTheme}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
              Switch to {isDark ? 'Light' : 'Dark'}
            </button>
          </div>
        </div>

        {/* Notification Preferences */}
        <div className="card">
          <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Bell size={18} color="var(--primary)" />
            <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600 }}>Home Alert Preferences</h3>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
            Control which automated home notices and routine deviation alerts trigger notifications.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', padding: '0.6rem 0.8rem', background: 'var(--bg-elevated)', borderRadius: '6px' }}>
              <div>
                <div style={{ fontWeight: 500, fontSize: '0.88rem' }}>Urgent Disruption Alerts</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Long inactivity, missed medicine routine, or safety events</div>
              </div>
              <input 
                type="checkbox" 
                checked={notifyUrgent} 
                onChange={(e) => handleTogglePref('pref_notify_urgent', e.target.checked, setNotifyUrgent)} 
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', padding: '0.6rem 0.8rem', background: 'var(--bg-elevated)', borderRadius: '6px' }}>
              <div>
                <div style={{ fontWeight: 500, fontSize: '0.88rem' }}>Daily Routine Summaries</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Show morning/evening pattern completion notices</div>
              </div>
              <input 
                type="checkbox" 
                checked={notifyRoutine} 
                onChange={(e) => handleTogglePref('pref_notify_routine', e.target.checked, setNotifyRoutine)} 
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', padding: '0.6rem 0.8rem', background: 'var(--bg-elevated)', borderRadius: '6px' }}>
              <div>
                <div style={{ fontWeight: 500, fontSize: '0.88rem' }}>Night Quiet Hours</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Suppress non-urgent notifications between 10 PM and 7 AM</div>
              </div>
              <input 
                type="checkbox" 
                checked={quietHours} 
                onChange={(e) => handleTogglePref('pref_quiet_hours', e.target.checked, setQuietHours)} 
              />
            </label>
          </div>
        </div>

        {/* System & Database Connectivity */}
        <div className="card">
          <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Database size={18} color="var(--primary)" />
            <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600 }}>System Health & Database</h3>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
            Truthful operational status of backend services and database storage.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.6rem 0.8rem', background: 'var(--bg-elevated)', borderRadius: '6px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Backend Service</span>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.35rem', color: health?.status === 'ok' ? 'var(--color-green, #10b981)' : 'var(--color-amber, #f59e0b)' }}>
                {health?.status === 'ok' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                {health?.status === 'ok' ? 'Online & Healthy' : 'Connecting...'}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.6rem 0.8rem', background: 'var(--bg-elevated)', borderRadius: '6px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Database Engine</span>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {typeof health?.database === 'object'
                  ? `${health.database.active_backend?.toUpperCase() || 'MYSQL'} (${health.database.is_mysql ? `Port ${health.database.mysql_port || 3306}` : 'SQLite'})`
                  : (health?.database || 'MySQL (Port 3306)')
                }
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.6rem 0.8rem', background: 'var(--bg-elevated)', borderRadius: '6px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>System Version</span>
              <span style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-primary)' }}>
                v{health?.version || '2.0.0'}
              </span>
            </div>
          </div>
        </div>

        {/* Connected Physical Hardware Devices */}
        <div className="card" style={{ gridColumn: '1 / -1' }}>
          <div className="card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Cpu size={18} color="var(--primary)" />
              <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600 }}>Connected IoT Sensor Nodes</h3>
            </div>
            <span className="badge badge-outline" style={{ fontSize: '0.75rem' }}>
              {devices.length} Registered Node{devices.length === 1 ? '' : 's'}
            </span>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
            Physical ESP32 hardware units installed in your home. Shows connectivity status, signal strength, and last communication.
          </p>

          {loading ? (
            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
              Checking connected sensor nodes...
            </div>
          ) : devices.length === 0 ? (
            <div style={{ padding: '1.5rem', background: 'var(--bg-elevated)', borderRadius: '8px', textAlign: 'center' }}>
              <Smartphone size={32} style={{ opacity: 0.4, marginBottom: '0.5rem' }} />
              <div style={{ fontWeight: 600 }}>No physical ESP32 nodes actively transmitting</div>
              <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                Hardware nodes register automatically when powered on and sending sensor heartbeats to the network.
              </div>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.85rem' }}>
              {devices.map((device, idx) => (
                <div key={device.device_id || idx} style={{ padding: '0.85rem 1rem', background: 'var(--bg-elevated)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{device.device_id || `Node #${idx + 1}`}</span>
                    <span className={`badge ${device.status === 'online' ? 'badge-success' : 'badge-neutral'}`} style={{ fontSize: '0.7rem' }}>
                      {device.status || 'unknown'}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    <div><strong>IP:</strong> {device.ip_address || 'DHCP'}</div>
                    <div><strong>Signal (RSSI):</strong> {device.rssi ? `${device.rssi} dBm` : 'N/A'}</div>
                    <div><strong>Last Seen:</strong> {device.last_seen ? new Date(device.last_seen).toLocaleTimeString() : 'N/A'}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
