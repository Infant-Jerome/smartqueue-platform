import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import Navbar from '../components/Navbar';
import { QueueStatusCard } from '../components/QueueStatusCard';
import { LoadingState, EmptyState, ErrorState } from '../components/States';
import { useQueueSocket } from '../hooks/useQueueSocket';

export default function Queue() {
  const [queueInfo, setQueueInfo] = useState(null);
  const [appointment, setAppointment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchAll = useCallback(async () => {
    try {
      const res = await api.get('/queue/my-position');
      const info = res.data;
      setQueueInfo(info);
      if (info?.has_queue) {
        try {
          const aRes = await api.get('/appointments');
          const list = Array.isArray(aRes.data) ? aRes.data : [];
          const active = list.find((a) =>
            ['booked', 'confirmed', 'waiting', 'serving', 'in_progress'].includes(
              String(a.status || '').toLowerCase()
            )
          );
          setAppointment(active || null);
        } catch {
          setAppointment(null);
        }
      } else {
        setAppointment(null);
      }
    } catch (err) {
      setError(err.message || 'Failed to load queue.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Live updates: any queue event refetches the authoritative REST state.
  const { connected } = useQueueSocket({
    salonId: appointment?.salon_id,
    barberId: appointment?.barber_id,
    date: appointment?.appointment_date,
    enabled: Boolean(queueInfo?.has_queue && appointment?.salon_id),
    onEvent: () => fetchAll(),
  });

  if (loading) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <LoadingState message="Loading queue..." />
      </div>
      </>
    );
  }

  if (error && !queueInfo) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <ErrorState message={error} onRetry={fetchAll} />
      </div>
      </>
    );
  }

  if (!queueInfo?.has_queue) {
    return (
      <><Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <div className="bg-white rounded-xl border border-slate-200">
          <EmptyState
            title="No Active Queue"
            message="Book an appointment to join the queue."
            action={<Link to="/book" className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 transition">Book Appointment</Link>}
          />
        </div>
      </div>
      </>
    );
  }

  return (
    <><Navbar />
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Live Queue</h1>
        <span className={`flex items-center gap-2 text-xs font-medium ${connected ? 'text-green-600' : 'text-slate-400'}`}>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-slate-300'}`}></span>
          {connected ? 'Live' : 'Polling'}
        </span>
      </div>

      <QueueStatusCard info={queueInfo} appointment={appointment} live={connected} />

      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <p className="text-sm text-slate-500 text-center">
          {connected ? 'Queue updates live as the shop serves customers' : 'Queue refreshes automatically'}
        </p>
      </div>
    </div>
    </>
  );
}
