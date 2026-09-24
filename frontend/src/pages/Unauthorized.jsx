import { Link } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getDashboardPath } from '../utils/roles';

export default function Unauthorized() {
  const { user } = useAuth();
  const home = user ? getDashboardPath(user.role) : '/login';

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md text-center bg-white rounded-2xl shadow-lg p-8">
        <div className="flex justify-center mb-4" aria-hidden="true">
          <span className="flex w-14 h-14 rounded-full bg-[var(--sq-danger-soft)] text-[var(--sq-danger)] items-center justify-center">
            <ShieldAlert size={28} />
          </span>
        </div>
        <h1 className="text-2xl font-bold text-slate-800 mb-2">Unauthorized</h1>
        <p className="text-slate-500 mb-6">You don&apos;t have permission to access this page.</p>
        <Link
          to={home}
          className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 transition"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
