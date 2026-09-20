import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import { appointmentId } from '../utils/format';
import { QueueStatusCard, ConfidenceBadge } from '../components/QueueStatusCard';
import { LoadingState, EmptyState } from '../components/States';
import { AppointmentCard } from '../components/AppointmentCard';

export default function Dashboard() {
  const { user } = useAuth();
  const [queueInfo, setQueueInfo] = useState(null);
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchAll = useCallback(async () => {
    setError('');
    try {
      const [qRes, aRes] = await Promise.all([
        api.get('/queue/my-position').catch(() => ({ data: null })),
        api.get('/appointments').catch(() => ({ data: [] })),
      ]);
      setQueueInfo(qRes.data);
      setAppointments(Array.isArray(aRes.data) ? aRes.data.slice(0, 5) : []);
    } catch {
      setError('Failed to load dashboard data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const upcoming = appointments.find((a) =>
    ['booked', 'confirmed', 'waiting'].includes(String(a.status || '').toLowerCase())
  );

  if (loading) return <><Navbar /><div className="max-w-7xl mx-auto px-4 py-8"><LoadingState message="Loading dashboard..." /></div></>;

  return (
    <>
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Welcome, {user?.name}</h1>
          <p className="text-slate-500">Here&apos;s your appointment overview</p>
        </div>
        <Link to="/notifications" className="text-sm text-blue-600 hover:text-blue-800 font-medium shrink-0 mt-1">
          Notifications
        </Link>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">{error}</div>
      )}

      {queueInfo?.has_queue && <QueueStatusCard info={queueInfo} compact />}

      <div className="grid md:grid-cols-4 gap-6 mb-8">
        <Link to="/book" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-blue-600 text-2xl mb-2">+</div>
          <h3 className="font-semibold text-slate-800">Book Appointment</h3>
          <p className="text-sm text-slate-500">Schedule a new visit</p>
        </Link>
        <Link to="/appointments" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-indigo-600 text-2xl mb-2">▤</div>
          <h3 className="font-semibold text-slate-800">My Appointments</h3>
          <p className="text-sm text-slate-500">View and manage bookings</p>
        </Link>
        <Link to="/queue" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-green-600 text-2xl mb-2">#</div>
          <h3 className="font-semibold text-slate-800">View Queue</h3>
          <p className="text-sm text-slate-500">Check your position</p>
        </Link>
        <Link to="/services" className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition">
          <div className="text-purple-600 text-2xl mb-2">*</div>
          <h3 className="font-semibold text-slate-800">Our Services</h3>
          <p className="text-sm text-slate-500">Browse available services</p>
        </Link>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h2 className="text-lg font-semibold text-slate-800 mb-4">Current Appointment</h2>
        {upcoming ? (
          <div className="space-y-4">
            <AppointmentCard appointment={upcoming} />
            {queueInfo?.has_queue && (
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <span>Estimated wait: <strong>{queueInfo.estimated_wait_minutes ?? '—'} min</strong></span>
                <ConfidenceBadge level={queueInfo.confidence} />
              </div>
            )}
          </div>
        ) : (
          <EmptyState
            title="No upcoming appointment"
            action={<Link to="/book" className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 transition">Book an Appointment</Link>}
          />
        )}
      </div>

      {appointments.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mt-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-slate-800">Recent Appointments</h2>
            <Link to="/appointments" className="text-sm text-blue-600 hover:text-blue-800 font-medium">View all</Link>
          </div>
          <div className="space-y-3">
            {appointments.map((appt) => (
              <Link key={appointmentId(appt)} to="/appointments" className="flex items-center justify-between p-3 bg-slate-50 rounded-lg hover:bg-slate-100 transition">
                <div>
                  <p className="font-medium text-slate-800">
                    {appt.service?.service_name || appt.service?.name || 'Service'} with {appt.barber?.name || 'Barber'}
                  </p>
                  <p className="text-sm text-slate-500">{String(appt.appointment_date).slice(0, 10)} at {String(appt.start_time || appt.appointment_time || '').slice(0, 5)}</p>
                </div>
                <span className="text-blue-600 text-sm font-medium">Details →</span>
              </Link>
            ))}
          </div>
        </div>
      )}
      </div>
    </>
  );
}
