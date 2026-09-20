import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getDashboardPath, normalizeRole } from '../utils/roles';

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const role = normalizeRole(user?.role);
  const isAdmin = role === 'admin';
  const isFrontDesk = role === 'staff' || role === 'receptionist';
  const isBarber = role === 'barber';

  return (
    <nav className="bg-white shadow-sm border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16 items-center">
          <div className="flex items-center gap-8">
            <Link to="/" className="text-xl font-bold text-blue-600">
              SmartQueue
            </Link>
            {user && (
              <div className="hidden md:flex gap-6">
                <Link to={getDashboardPath(user.role)} className="text-slate-600 hover:text-blue-600 text-sm font-medium">Dashboard</Link>
                <Link to="/services" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Services</Link>
                <Link to="/barbers" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Barbers</Link>
                {(role === 'customer' || isFrontDesk || isAdmin) && (
                  <Link to="/book" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Book</Link>
                )}
                <Link to="/queue" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Queue</Link>
                {(role === 'customer' || isAdmin) && (
                  <Link to="/appointments" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Appointments</Link>
                )}
                {(role === 'customer' || isAdmin) && (
                  <Link to="/notifications" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Notifications</Link>
                )}
                {isFrontDesk && (
                  <Link to="/receptionist/dashboard" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Desk</Link>
                )}
                {isBarber && (
                  <Link to="/barber/dashboard" className="text-slate-600 hover:text-blue-600 text-sm font-medium">My Queue</Link>
                )}
                {isAdmin && (
                  <Link to="/admin/dashboard" className="text-slate-600 hover:text-blue-600 text-sm font-medium">Admin</Link>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-4">
            {user ? (
              <>
                <span className="text-sm text-slate-500">Hi, {user.name}</span>
                <button onClick={handleLogout} className="text-sm text-red-500 hover:text-red-700 font-medium">Logout</button>
              </>
            ) : (
              <>
                <Link to="/login" className="text-sm text-blue-600 hover:text-blue-800 font-medium">Login</Link>
                <Link to="/register" className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium">Register</Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
