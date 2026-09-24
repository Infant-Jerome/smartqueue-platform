import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getDashboardPath, normalizeRole } from '../utils/roles';

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLogout = () => {
    setMenuOpen(false);
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
                <span className="hidden sm:inline text-sm text-slate-500">Hi, {user.name}</span>
                <button onClick={handleLogout} className="hidden sm:inline text-sm text-red-500 hover:text-red-700 font-medium">Logout</button>
                <button
                  onClick={() => setMenuOpen((v) => !v)}
                  aria-label={menuOpen ? 'Close menu' : 'Open menu'}
                  aria-expanded={menuOpen}
                  className="sm:hidden p-2 -mr-2 text-slate-600 hover:text-slate-900 leading-none min-w-[2.75rem] min-h-[2.75rem] inline-flex items-center justify-center"
                >
                  {menuOpen ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="text-sm text-blue-600 hover:text-blue-800 font-medium">Login</Link>
                <Link to="/register" className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium">Register</Link>
              </>
            )}
          </div>
        </div>
        {user && menuOpen && (
          <div className="sm:hidden pb-4 flex flex-col gap-1">
            <Link to={getDashboardPath(user.role)} onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Dashboard</Link>
            <Link to="/services" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Services</Link>
            <Link to="/barbers" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Barbers</Link>
            {(role === 'customer' || isFrontDesk || isAdmin) && (
              <Link to="/book" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Book</Link>
            )}
            <Link to="/queue" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Queue</Link>
            {(role === 'customer' || isAdmin) && (
              <>
                <Link to="/appointments" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Appointments</Link>
                <Link to="/notifications" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Notifications</Link>
              </>
            )}
            {isFrontDesk && (
              <Link to="/receptionist/dashboard" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Desk</Link>
            )}
            {isBarber && (
              <Link to="/barber/dashboard" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">My Queue</Link>
            )}
            {isAdmin && (
              <Link to="/admin/dashboard" onClick={() => setMenuOpen(false)} className="px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Admin</Link>
            )}
            <button onClick={handleLogout} className="text-left px-2 py-2 text-sm font-medium text-red-500 hover:bg-red-50 rounded-lg">Logout</button>
          </div>
        )}
      </div>
    </nav>
  );
}
