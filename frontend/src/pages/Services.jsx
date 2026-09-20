import { useState, useEffect } from 'react';
import api from '../services/api';
import { ServiceGrid } from '../components/ServiceCard';
import { LoadingState, EmptyState, ErrorState } from '../components/States';

export default function Services() {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchAll = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get('/services');
      setServices(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err.message || 'Failed to load services.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <LoadingState message="Loading services..." />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800">Our Services</h1>
        <p className="text-slate-500">Choose from our range of professional grooming services</p>
      </div>
      {error ? (
        <ErrorState message={error} onRetry={fetchAll} />
      ) : services.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200">
          <EmptyState title="No services available" message="Please check back later." />
        </div>
      ) : (
        <ServiceGrid services={services} />
      )}
    </div>
  );
}
