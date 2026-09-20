import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getDashboardPath } from '../utils/roles';

export default function Unauthorized() {
  const { user } = useAuth();
  const home = user ? getDashboardPath(user.role) : '/login';

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md text-center bg-white rounded-2xl shadow-lg p-8">
        <div className="text-5xl mb-4">🚫</div>
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
