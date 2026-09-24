import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import { getDashboardPath } from './utils/roles';
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import Dashboard from './pages/Dashboard';
import Services from './pages/Services';
import Barbers from './pages/Barbers';
import BookAppointment from './pages/BookAppointment';
import Appointments from './pages/Appointments';
import Queue from './pages/Queue';
import Notifications from './pages/Notifications';
import Admin from './pages/Admin';
import BarberDashboard from './pages/BarberDashboard';
import ReceptionistDashboard from './pages/ReceptionistDashboard';
import Unauthorized from './pages/Unauthorized';

function Landing() {
  const { user } = useAuth();
  if (user) return <Navigate to={getDashboardPath(user.role)} replace />;
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 to-blue-800 flex items-center justify-center px-4">
      <div className="text-center text-white">
        <h1 className="text-5xl font-bold mb-4">SmartQueue</h1>
        <p className="text-xl text-blue-200 mb-8 max-w-lg">Barbershop appointment booking &amp; queue management — skip the wait, book your slot.</p>
        <div className="flex gap-4 justify-center">
          <a href="/login" className="bg-white text-blue-600 px-8 py-3 rounded-lg font-semibold hover:bg-blue-50 transition">Sign In</a>
          <a href="/register" className="border-2 border-white text-white px-8 py-3 rounded-lg font-semibold hover:bg-white/10 transition">Get Started</a>
        </div>
      </div>
    </div>
  );
}

function RoleLanding() {
  const { user } = useAuth();
  return <Navigate to={getDashboardPath(user?.role)} replace />;
}

function AppRoutes() {
  const { user } = useAuth();
  const home = getDashboardPath(user?.role);
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={user ? <Navigate to={home} replace /> : <Login />} />
      <Route path="/register" element={user ? <Navigate to={home} replace /> : <Register />} />
      <Route path="/forgot-password" element={user ? <Navigate to={home} replace /> : <ForgotPassword />} />
      <Route path="/unauthorized" element={<Unauthorized />} />
      {/* Customer */}
      <Route path="/dashboard" element={<ProtectedRoute roles={['customer']}><Dashboard /></ProtectedRoute>} />
      {/* Barber */}
      <Route path="/barber/dashboard" element={<ProtectedRoute roles={['barber']}><BarberDashboard /></ProtectedRoute>} />
      {/* Receptionist (staff alias shares this dashboard) */}
      <Route path="/receptionist/dashboard" element={<ProtectedRoute roles={['receptionist', 'staff']}><ReceptionistDashboard /></ProtectedRoute>} />
      {/* Admin */}
      <Route path="/admin/dashboard" element={<ProtectedRoute roles={['admin']}><Admin /></ProtectedRoute>} />
      <Route path="/admin" element={<RoleLanding />} />
      {/* Shared authenticated areas */}
      <Route path="/services" element={<Services />} />
      <Route path="/barbers" element={<Barbers />} />
      <Route path="/book" element={<ProtectedRoute><BookAppointment /></ProtectedRoute>} />
      <Route path="/appointments" element={<ProtectedRoute roles={['customer']}><Appointments /></ProtectedRoute>} />
      <Route path="/queue" element={<ProtectedRoute><Queue /></ProtectedRoute>} />
      <Route path="/notifications" element={<ProtectedRoute roles={['customer']}><Notifications /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Router>
        <div className="min-h-screen bg-slate-50">
          <AppRoutes />
        </div>
      </Router>
    </AuthProvider>
  );
}
