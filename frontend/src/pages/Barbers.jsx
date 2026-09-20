import { useState, useEffect } from 'react';
import api from '../services/api';
import Navbar from '../components/Navbar';
import { BarberGrid } from '../components/BarberCard';
import { LoadingState, EmptyState, ErrorState } from '../components/States';

export default function Barbers() {
  const [barbers, setBarbers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchAll = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get('/barbers');
      setBarbers(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err.message || 'Failed to load barbers.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  if (loading) {
    return (
      <><Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
        <LoadingState message="Loading barbers..." />
      </div>
      </>
    );
  }

  return (
    <><Navbar />
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800">Our Barbers</h1>
        <p className="text-slate-500">Meet our professional team</p>
      </div>
      {error ? (
        <ErrorState message={error} onRetry={fetchAll} />
      ) : barbers.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200">
          <EmptyState title="No barbers available" message="Please check back later." />
        </div>
      ) : (
        <BarberGrid barbers={barbers} />
      )}
    </div>
    </>
  );
}
