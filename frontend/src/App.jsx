import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import OverviewDashboard from './pages/OverviewDashboard';
import LiveSensorMonitoring from './pages/LiveSensorMonitoring';
import ActivityRecognition from './pages/ActivityRecognition';
import RoutineAnalysis from './pages/RoutineAnalysis';
import AnomalyDetection from './pages/AnomalyDetection';
import DatasetManagement from './pages/DatasetManagement';
import SystemArchitecture from './pages/SystemArchitecture';
import ModelTraining from './pages/ModelTraining';
import AlertCentre from './pages/AlertCentre';
import Explainability from './pages/Explainability';
import Settings from './pages/Settings';
import { ToastProvider } from './hooks/useToast';
import { ThemeProvider } from './context/ThemeContext';
import { getAnomalyAlerts, getPhase2Alerts } from './services/api';

function AppContent() {
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const [legacyData, phase2Data] = await Promise.all([
          getAnomalyAlerts({ status: 'active', limit: 100 }),
          getPhase2Alerts({ tier: 'CONFIRMED' }),
        ]);
        const total = (legacyData.alerts?.length || 0) + (phase2Data.alerts?.length || 0);
        setAlertCount(total);
      } catch { /* ignore */ }
    };
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-shell">
      <Sidebar alertCount={alertCount} />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<OverviewDashboard />} />
          <Route path="/sensors" element={<LiveSensorMonitoring />} />
          <Route path="/recognition" element={<ActivityRecognition />} />
          <Route path="/routine" element={<RoutineAnalysis />} />
          <Route path="/anomalies" element={<AnomalyDetection />} />
          <Route path="/datasets" element={<DatasetManagement />} />
          <Route path="/architecture" element={<SystemArchitecture />} />
          {/* Phase 2 pages */}
          <Route path="/training" element={<ModelTraining />} />
          <Route path="/alerts" element={<AlertCentre />} />
          <Route path="/explain" element={<Explainability />} />
          <Route path="/history" element={<ActivityRecognition />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Router>
      <ThemeProvider>
        <ToastProvider>
          <AppContent />
        </ToastProvider>
      </ThemeProvider>
    </Router>
  );
}

