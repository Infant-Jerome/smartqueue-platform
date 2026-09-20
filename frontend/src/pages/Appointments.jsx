import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import Navbar from '../components/Navbar';
import { appointmentId, fmtDate, fmtTime, prettyStatus } from '../utils/format';
import { AppointmentCard } from '../components/AppointmentCard';
import { LoadingState, EmptyState, ErrorState } from '../components/States';

export default function Appointments() {
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [cancellingId, setCancellingId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [notice, setNotice] = useState('');

  const fetchAll = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await api.get('/appointments');
      setAppointments(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err.message || 'Failed to load appointments.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const handleCancel = async (id) => {
    setCancellingId(id);
    setNotice('');
    try {
      await api.delete(`/appointments/${id}`);
      setConfirmId(null);
      setNotice('Appointment cancelled.');
      await fetchAll();
    } catch (err) {
      setError(err.message || 'Cancellation failed.');
    } finally {
      setCancellingId(null);
    }
  };

  if (loading) return <><Navbar /><div className="max-w-4xl mx-auto px-4 py-8"><LoadingState message="Loading appointments..." /></div></>;

  return (
    <><Navbar />
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">My Appointments</h1>
          <p className="text-slate-500">Your bookings and their live status</p>
        </div>
        <Link to="/book" className="bg-blue-600 text-white px-5 py-2 rounded-lg font-medium hover:bg-blue-700 transition text-sm">
          + New Booking
        </Link>
      </div>

      {notice && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">{notice}</div>
      )}
      {error && (
        <div className="mb-4">
          <ErrorState message={error} onRetry={fetchAll} />
        </div>
      )}

      {appointments.length === 0 && !error ? (
        <div className="bg-white rounded-xl border border-slate-200">
          <EmptyState
            title="No appointments yet"
            message="Book your first appointment to get started."
            action={<Link to="/book" className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 transition">Book an Appointment</Link>}
          />
        </div>
      ) : (
        <div className="space-y-4">
          {appointments.map((a) => (
            <div key={appointmentId(a)}>
              <AppointmentCard
                appointment={a}
                cancelling={cancellingId === appointmentId(a)}
                onCancel={(id) => setConfirmId(id)}
              />
              {confirmId === appointmentId(a) && (
                <div className="bg-red-50 border border-red-200 rounded-xl p-4 mt-2 flex flex-col sm:flex-row sm:items-center gap-3">
                  <p className="text-sm text-slate-700 flex-1">
                    Cancel this appointment on {fmtDate(a.appointment_date)} at {fmtTime(a.start_time)} ({prettyStatus(a.status)})?
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => setConfirmId(null)} className="px-4 py-2 text-sm bg-white border border-slate-300 rounded-lg hover:bg-slate-50">Keep</button>
                    <button onClick={() => handleCancel(appointmentId(a))} disabled={cancellingId} className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50">Confirm cancel</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
    </>
  );
}
