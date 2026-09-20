import { useState, useEffect } from 'react';
import api from '../services/api';
import { LoadingState, EmptyState, ErrorState } from '../components/States';

const CHANNEL_STYLES = {
  email: 'bg-blue-100 text-blue-700',
  push: 'bg-purple-100 text-purple-700',
  sms: 'bg-green-100 text-green-700',
};

function prettyType(t) {
  return String(t || '—').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function Notifications() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchAll = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get('/notifications');
      setItems(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err.message || 'Failed to load notifications.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  if (loading) return <div className="max-w-4xl mx-auto px-4 py-8"><LoadingState message="Loading notifications..." /></div>;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-800 mb-2">Notifications</h1>
      <p className="text-slate-500 mb-6">Updates about your appointments and queue</p>

      {error && <ErrorState message={error} onRetry={fetchAll} />}

      {!error && items.length === 0 && (
        <div className="bg-white rounded-xl border border-slate-200">
          <EmptyState title="No notifications yet" message="Booking and queue updates will appear here." />
        </div>
      )}

      <div className="space-y-3">
        {items.map((n) => (
          <div key={n.notification_id ?? `${n.type}-${n.created_at}`} className="bg-white rounded-xl border border-slate-200 p-5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-slate-800">{prettyType(n.type)}</span>
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${CHANNEL_STYLES[String(n.channel || '').toLowerCase()] || 'bg-slate-100 text-slate-600'}`}>
                {String(n.channel || '—').toUpperCase()}
              </span>
              <span className="ml-auto text-xs text-slate-400">
                {n.created_at ? String(n.created_at).slice(0, 16).replace('T', ' ') : ''}
              </span>
            </div>
            {(n.subject || n.body) && (
              <p className="text-sm text-slate-600 mt-2">{n.subject || n.body}</p>
            )}
            <p className="text-xs text-slate-400 mt-2 capitalize">Status: {n.status || '—'}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
