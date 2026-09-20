import { useState, useEffect, useCallback, useMemo } from 'react';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { LoadingState, EmptyState, ErrorState } from '../components/States';
import { ConfidenceBadge } from '../components/QueueStatusCard';
import { statusStyle, prettyStatus, fmtTime } from '../utils/format';
import { useQueueSocket } from '../hooks/useQueueSocket';

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function displayDate() {
  return new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

const FILTERS = ['All', 'Waiting', 'Serving', 'Completed', 'Cancelled', 'No Show'];
const FILTER_STATUS = { Waiting: 'waiting', Serving: 'serving', Completed: 'completed', Cancelled: 'cancelled', 'No Show': 'no_show' };

function ActionButton({ onClick, busy, children, tone = 'primary', title }) {
  const tones = {
    primary: 'bg-blue-600 hover:bg-blue-700 text-white',
    success: 'bg-green-600 hover:bg-green-700 text-white',
    danger: 'bg-red-50 hover:bg-red-100 text-red-600 border border-red-200',
    subtle: 'bg-slate-100 hover:bg-slate-200 text-slate-700',
  };
  return (
    <button onClick={onClick} disabled={busy} title={title}
      className={`px-2.5 py-1 rounded-lg text-xs font-medium transition disabled:opacity-50 ${tones[tone]}`}>
      {busy ? '...' : children}
    </button>
  );
}

/**
 * Receptionist / staff operational dashboard (Frontend Phase 4).
 * Salon-scoped overview using only staff-authorized endpoints.
 * Backend owns queue state, SAWTE estimates and RBAC; this page displays
 * backend values verbatim and calls existing operational endpoints.
 */
export default function ReceptionistDashboard() {
  const { user } = useAuth();
  const today = useMemo(() => todayStr(), []);

  const [appointments, setAppointments] = useState([]);
  const [queue, setQueue] = useState([]);
  const [barbers, setBarbers] = useState([]);
  const [services, setServices] = useState({});
  const [availability, setAvailability] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState({});
  const [statusFilter, setStatusFilter] = useState('All');
  const [barberFilter, setBarberFilter] = useState('All');

  const serviceOf = useCallback((id) => services[id], [services]);
  const barberOf = useCallback((id) => barbers.find((b) => b.barber_id === id), [barbers]);

  const salonId = useMemo(() => {
    const ids = [
      ...barbers.map((b) => b.salon_id),
      ...appointments.map((a) => a.salon_id),
    ].filter((v) => v != null);
    return ids.length ? [...new Set(ids)][0] : null;
  }, [barbers, appointments]);

  const fetchAll = useCallback(async () => {
    setError('');
    try {
      const [aRes, bRes, sRes] = await Promise.all([
        api.get('/appointments'),
        api.get('/barbers').catch(() => ({ data: [] })),
        api.get('/services').catch(() => ({ data: [] })),
      ]);
      const appts = Array.isArray(aRes.data) ? aRes.data : [];
      const barberList = Array.isArray(bRes.data) ? bRes.data : [];
      setAppointments(appts);
      setBarbers(barberList);
      const map = {};
      for (const s of Array.isArray(sRes.data) ? sRes.data : []) map[s.service_id] = s;
      setServices(map);

      const params = { date: today };
      if (statusFilter !== 'All') params.status = FILTER_STATUS[statusFilter];
      if (barberFilter !== 'All') params.barber_id = Number(barberFilter);
      const qRes = await api.get('/queue', { params }).catch(() => ({ data: [] }));
      setQueue(Array.isArray(qRes.data) ? qRes.data : []);

      const vRes = await api.get('/availability', { params: { date: today } }).catch(() => ({ data: [] }));
      setAvailability(Array.isArray(vRes.data) ? vRes.data : []);
    } catch (err) {
      setError(err.message || 'Unable to load dashboard data.');
    } finally {
      setLoading(false);
    }
  }, [today, statusFilter, barberFilter]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Live updates: any queue event refetches authoritative REST state.
  const { connected } = useQueueSocket({
    salonId,
    date: today,
    enabled: Boolean(salonId),
    onEvent: () => fetchAll(),
  });

  const todaysAppointments = useMemo(
    () =>
      appointments
        .filter((a) => String(a.appointment_date).slice(0, 10) === today)
        .sort((x, y) => String(x.start_time).localeCompare(String(y.start_time))),
    [appointments, today]
  );

  const countStatus = (list, key, values) =>
    list.filter((x) => values.includes(String(x[key] || '').toLowerCase())).length;
  const waitingCount = countStatus(todaysAppointments, 'status', ['waiting', 'booked', 'confirmed']);
  const servingCount = countStatus(queue, 'status', ['serving', 'in_progress']);
  const completedCount = countStatus(todaysAppointments, 'status', ['completed']);
  const cancelledCount = countStatus(todaysAppointments, 'status', ['cancelled']);
  const noShowCount = countStatus(todaysAppointments, 'status', ['no_show']);

  const servingEntries = queue.filter((q) => ['serving', 'in_progress'].includes(String(q.status).toLowerCase()));
  const apptById = useMemo(() => {
    const map = {};
    for (const a of appointments) map[a.appointment_id] = a;
    return map;
  }, [appointments]);

  const runAction = async (key, fn, successMsg) => {
    setPending((p) => ({ ...p, [key]: true }));
    setActionError('');
    setNotice('');
    try {
      await fn();
      setNotice(successMsg);
      await fetchAll();
    } catch (err) {
      setActionError(err.message || 'Action could not be completed.');
    } finally {
      setPending((p) => ({ ...p, [key]: false }));
    }
  };

  const serveNextFor = (barberId) =>
    runAction(`next-${barberId}`, () => api.post('/queue/serve-next', { barber_id: barberId }), 'Next customer is being served.');
  const serveEntry = (qid) =>
    runAction(`serve-${qid}`, () => api.post(`/queue/${qid}/serve`), 'Customer is being served.');
  const completeEntry = (qid) =>
    runAction(`complete-${qid}`, () => api.post(`/queue/${qid}/complete`), 'Service completed.');
  const skipEntry = (qid) =>
    runAction(`skip-${qid}`, () => api.post(`/queue/${qid}/skip`), 'Customer marked as no-show.');

  const queueForBarber = (barberId) => queue.filter((q) => q.barber_id === barberId);
  const availForBarber = (barberId) =>
    availability.filter((v) => v.barber_id === barberId && String(v.date).slice(0, 10) === today);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-8"><LoadingState message="Loading reception dashboard..." /></main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">Receptionist Dashboard</h1>
            <p className="text-slate-500 mt-1">{displayDate()}{user?.name ? ` · ${user.name}` : ''}</p>
          </div>
          <span className={`flex items-center gap-2 text-xs font-medium ${connected ? 'text-green-600' : 'text-slate-400'}`}>
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-slate-300'}`}></span>
            {connected ? 'Live' : 'Live updates temporarily unavailable'}
          </span>
        </div>

        {error && (
          <div className="mb-4"><ErrorState message={error} onRetry={fetchAll} /></div>
        )}
        {actionError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">{actionError}</div>
        )}
        {notice && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">{notice}</div>
        )}

        {/* Summary */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          {[
            { label: "Today's Appointments", value: todaysAppointments.length },
            { label: 'Waiting', value: waitingCount },
            { label: 'Serving', value: servingCount },
            { label: 'Completed', value: completedCount },
            { label: 'Cancelled / No-show', value: cancelledCount + noShowCount },
          ].map((c) => (
            <div key={c.label} className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
              <p className="text-slate-500 text-sm">{c.label}</p>
              <p className="text-3xl font-bold text-slate-800 mt-1">{c.value}</p>
            </div>
          ))}
        </div>

        {/* Currently serving */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Currently Serving</h2>
          {servingEntries.length === 0 ? (
            <EmptyState title="No customers are currently being served." />
          ) : (
            <div className="grid md:grid-cols-2 gap-3">
              {servingEntries.map((q) => {
                const appt = apptById[q.appointment_id] || {};
                const svc = appt.service_id != null ? serviceOf(appt.service_id) : undefined;
                const barb = barberOf(q.barber_id);
                return (
                  <div key={q.queue_id} className="p-4 bg-green-50 border border-green-200 rounded-xl">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-semibold text-slate-800">Queue #{q.queue_position} · {barb?.name || `Barber #${q.barber_id}`}</p>
                      <ActionButton onClick={() => completeEntry(q.queue_id)} busy={pending[`complete-${q.queue_id}`]} tone="success">
                        Complete
                      </ActionButton>
                    </div>
                    <p className="text-sm text-slate-600 mt-1">
                      Appt #{q.appointment_id} · {svc?.service_name || 'Service'}
                      {appt.start_time ? ` · ${fmtTime(appt.start_time)}` : ''}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Live queue + filters */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <h2 className="text-lg font-semibold text-slate-800 mr-auto">Live Queue</h2>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
              {FILTERS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <select value={barberFilter} onChange={(e) => setBarberFilter(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
              <option value="All">All barbers</option>
              {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
            </select>
          </div>
          {queue.length === 0 ? (
            <EmptyState title="No customers are currently waiting." />
          ) : (
            <div className="space-y-2">
              {[...queue].sort((a, b) => a.queue_position - b.queue_position).map((q) => {
                const st = String(q.status).toLowerCase();
                const appt = apptById[q.appointment_id] || {};
                const svc = appt.service_id != null ? serviceOf(appt.service_id) : undefined;
                const barb = barberOf(q.barber_id);
                return (
                  <div key={q.queue_id} className="flex flex-wrap items-center gap-3 p-3 bg-slate-50 rounded-xl">
                    <div className="w-9 h-9 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold shrink-0">
                      {q.queue_position}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-slate-800 text-sm">
                        Appt #{q.appointment_id} · {barb?.name || `Barber #${q.barber_id}`} · {svc?.service_name || 'Service'}
                      </p>
                      <p className="text-xs text-slate-500">
                        {appt.start_time ? `${fmtTime(appt.start_time)} · ` : ''}
                        {svc?.duration_minutes != null ? `${svc.duration_minutes} min · ` : ''}
                        {q.estimated_wait_minutes != null ? `~${q.estimated_wait_minutes} min wait` : 'Calculating...'}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusStyle(q.status)}`}>
                          {prettyStatus(q.status)}
                        </span>
                        {q.confidence && <ConfidenceBadge level={q.confidence} />}
                      </div>
                    </div>
                    <div className="flex gap-1.5">
                      {st === 'waiting' && (
                        <ActionButton onClick={() => serveEntry(q.queue_id)} busy={pending[`serve-${q.queue_id}`]}>
                          Serve
                        </ActionButton>
                      )}
                      {(st === 'serving' || st === 'in_progress') && (
                        <ActionButton onClick={() => completeEntry(q.queue_id)} busy={pending[`complete-${q.queue_id}`]} tone="success">
                          Complete
                        </ActionButton>
                      )}
                      {st === 'waiting' && (
                        <ActionButton onClick={() => skipEntry(q.queue_id)} busy={pending[`skip-${q.queue_id}`]} tone="danger">
                          Skip
                        </ActionButton>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Barber overview */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Barbers</h2>
          {barbers.length === 0 ? (
            <EmptyState title="No barber data available." />
          ) : (
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
              {barbers.map((b) => {
                const rows = queueForBarber(b.barber_id);
                const w = rows.filter((q) => String(q.status).toLowerCase() === 'waiting').length;
                const s = rows.filter((q) => ['serving', 'in_progress'].includes(String(q.status).toLowerCase())).length;
                const wins = availForBarber(b.barber_id);
                return (
                  <div key={b.barber_id} className="border border-slate-200 rounded-xl p-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center shrink-0">
                        <span className="text-blue-600 font-bold">{(b.name || '?').charAt(0)}</span>
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-800 truncate">{b.name}</p>
                        <p className="text-xs text-slate-500 truncate">
                          {b.specialization || 'General'} · Availability: <span className="capitalize">{b.availability_status}</span>
                        </p>
                      </div>
                    </div>
                    <p className="text-sm text-slate-600 mt-3">
                      Waiting: <strong>{w}</strong> · Serving: <strong>{s}</strong>
                    </p>
                    <p className="text-xs text-slate-500 mt-1">
                      Today: {wins.length ? wins.map((x) => `${fmtTime(x.start_time)}–${fmtTime(x.end_time)}`).join(', ') : 'no windows listed'}
                    </p>
                    <button
                      onClick={() => serveNextFor(b.barber_id)}
                      disabled={pending[`next-${b.barber_id}`]}
                      className="mt-3 w-full bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition"
                    >
                      {pending[`next-${b.barber_id}`] ? 'Serving...' : 'Serve Next Customer'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Today's appointments */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Today&apos;s Appointments</h2>
          {todaysAppointments.length === 0 ? (
            <EmptyState title="No appointments scheduled for today." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-100">
                    <th className="py-2 pr-4 font-medium">Time</th>
                    <th className="py-2 pr-4 font-medium">Appt</th>
                    <th className="py-2 pr-4 font-medium">Barber</th>
                    <th className="py-2 pr-4 font-medium">Service</th>
                    <th className="py-2 pr-4 font-medium">Duration</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {todaysAppointments.map((a) => {
                    const svc = a.service_id != null ? serviceOf(a.service_id) : undefined;
                    const barb = barberOf(a.barber_id);
                    const st = String(a.status || '').toLowerCase();
                    const q = queue.find((x) => x.appointment_id === a.appointment_id);
                    const terminal = ['completed', 'cancelled', 'no_show'].includes(st);
                    return (
                      <tr key={a.appointment_id} className="border-b border-slate-50">
                        <td className="py-2 pr-4 font-medium text-slate-800 whitespace-nowrap">
                          {fmtTime(a.start_time)}{a.end_time ? ` – ${fmtTime(a.end_time)}` : ''}
                        </td>
                        <td className="py-2 pr-4 text-slate-600">#{a.appointment_id}</td>
                        <td className="py-2 pr-4 text-slate-600">{barb?.name || `#${a.barber_id}`}</td>
                        <td className="py-2 pr-4 text-slate-600">{svc?.service_name || '—'}</td>
                        <td className="py-2 pr-4 text-slate-600">{svc?.duration_minutes != null ? `${svc.duration_minutes} min` : '—'}</td>
                        <td className="py-2 pr-4">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusStyle(a.status)}`}>
                            {prettyStatus(a.status)}
                          </span>
                          {q && <span className="text-xs text-slate-400 ml-1">Q#{q.queue_position}</span>}
                        </td>
                        <td className="py-2">
                          {!terminal && (
                            <div className="flex gap-1.5">
                              {st === 'booked' && (
                                <ActionButton onClick={() => runAction(`confirm-${a.appointment_id}`, () => api.put(`/appointments/${a.appointment_id}`, { status: 'confirmed' }), 'Appointment confirmed.')} busy={pending[`confirm-${a.appointment_id}`]} tone="subtle">
                                  Confirm
                                </ActionButton>
                              )}
                              <ActionButton onClick={() => runAction(`cancel-${a.appointment_id}`, () => api.delete(`/appointments/${a.appointment_id}`), 'Appointment cancelled.')} busy={pending[`cancel-${a.appointment_id}`]} tone="danger">
                                Cancel
                              </ActionButton>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
