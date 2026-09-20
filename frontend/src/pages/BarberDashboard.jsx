import { useState, useEffect, useCallback, useMemo } from 'react';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { LoadingState, EmptyState, ErrorState } from '../components/States';
import { ConfidenceBadge } from '../components/QueueStatusCard';
import { statusStyle, prettyStatus, fmtTime, fmtDate } from '../utils/format';
import { useQueueSocket } from '../hooks/useQueueSocket';

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function displayDate() {
  return new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

const TERMINAL_QUEUE = new Set(['completed', 'cancelled', 'no_show']);

function ActionButton({ onClick, disabled, busy, children, tone = 'primary' }) {
  const tones = {
    primary: 'bg-blue-600 hover:bg-blue-700 text-white',
    success: 'bg-green-600 hover:bg-green-700 text-white',
    danger: 'bg-red-50 hover:bg-red-100 text-red-600 border border-red-200',
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled || busy}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-50 ${tones[tone]}`}
    >
      {busy ? 'Working...' : children}
    </button>
  );
}

/**
 * Barber operational dashboard (Frontend Phase 3).
 * Backend is authoritative for queue state, SAWTE estimates and RBAC;
 * this page only displays backend values and calls existing endpoints.
 */
export default function BarberDashboard() {
  const { user } = useAuth();
  const today = useMemo(() => todayStr(), []);

  const [profile, setProfile] = useState(null);
  const [appointments, setAppointments] = useState([]);
  const [queue, setQueue] = useState([]);
  const [services, setServices] = useState({});
  const [availability, setAvailability] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState({});
  const [availForm, setAvailForm] = useState({ date: todayStr(), start_time: '', end_time: '' });
  const [availBusy, setAvailBusy] = useState(false);

  const serviceOf = useCallback((serviceId) => services[serviceId], [services]);

  const fetchAll = useCallback(async () => {
    setError('');
    try {
      const bRes = await api.get('/barbers');
      const list = Array.isArray(bRes.data) ? bRes.data : [];
      const mine = list.find((b) => b.user_id != null && b.user_id === user?.user_id) || null;
      setProfile(mine);

      const [aRes, sRes] = await Promise.all([
        api.get('/appointments'),
        api.get('/services').catch(() => ({ data: [] })),
      ]);
      const appts = Array.isArray(aRes.data) ? aRes.data : [];
      setAppointments(appts);
      const map = {};
      for (const s of Array.isArray(sRes.data) ? sRes.data : []) map[s.service_id] = s;
      setServices(map);

      if (mine) {
        const [qRes, vRes] = await Promise.all([
          api.get('/queue', { params: { barber_id: mine.barber_id, date: today } }).catch(() => ({ data: [] })),
          api.get('/availability', { params: { barber_id: mine.barber_id, date: today } }).catch(() => ({ data: [] })),
        ]);
        setQueue(Array.isArray(qRes.data) ? qRes.data : []);
        setAvailability(Array.isArray(vRes.data) ? vRes.data : []);
      }
    } catch (err) {
      setError(err.message || 'Unable to load dashboard data.');
    } finally {
      setLoading(false);
    }
  }, [user?.user_id, today]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Live updates: any queue event refetches authoritative REST state.
  const { connected } = useQueueSocket({
    salonId: profile?.salon_id,
    barberId: profile?.barber_id,
    date: today,
    enabled: Boolean(profile?.salon_id && profile?.barber_id),
    onEvent: () => fetchAll(),
  });

  const todaysAppointments = useMemo(
    () =>
      appointments
        .filter((a) => String(a.appointment_date).slice(0, 10) === today)
        .sort((x, y) => String(x.start_time).localeCompare(String(y.start_time))),
    [appointments, today]
  );

  // Queue rows carry appointment_id; join service/time details from the
  // already-fetched appointments (backend QueueResponse may not nest them).
  const apptById = useMemo(() => {
    const map = {};
    for (const a of appointments) map[a.appointment_id] = a;
    return map;
  }, [appointments]);

  const entryDetails = useCallback((entry) => {
    const appt = { ...(apptById[entry.appointment_id] || {}), ...(entry.appointment || {}) };
    return { appt, service: appt.service_id != null ? serviceOf(appt.service_id) : undefined };
  }, [apptById, serviceOf]);

  const waiting = queue.filter((q) => String(q.status).toLowerCase() === 'waiting');
  const serving = queue.find((q) => ['serving', 'in_progress'].includes(String(q.status).toLowerCase())) || null;
  const completedToday = queue.filter((q) => String(q.status).toLowerCase() === 'completed').length
    + todaysAppointments.filter((a) => String(a.status).toLowerCase() === 'completed').length;

  const runAction = async (key, fn, successMsg) => {
    setPending((p) => ({ ...p, [key]: true }));
    setActionError('');
    setNotice('');
    try {
      await fn();
      setNotice(successMsg);
      await fetchAll();
    } catch (err) {
      setActionError(err.message || 'Action failed.');
    } finally {
      setPending((p) => ({ ...p, [key]: false }));
    }
  };

  const serveNext = () =>
    runAction('next', () => api.post('/queue/serve-next', { barber_id: profile.barber_id }), 'Next customer is being served.');
  const serveEntry = (qid) =>
    runAction(`serve-${qid}`, () => api.post(`/queue/${qid}/serve`), 'Customer is being served.');
  const completeEntry = (qid) =>
    runAction(`complete-${qid}`, () => api.post(`/queue/${qid}/complete`), 'Service completed.');
  const skipEntry = (qid) =>
    runAction(`skip-${qid}`, () => api.post(`/queue/${qid}/skip`), 'Customer marked as no-show.');

  const toggleAvailability = (row) =>
    runAction(
      `avail-${row.availability_id}`,
      () => api.put(`/availability/${row.availability_id}`, {
        status: String(row.status).toLowerCase() === 'available' ? 'unavailable' : 'available',
      }),
      'Availability updated.'
    );

  const createAvailability = async (e) => {
    e.preventDefault();
    setActionError('');
    if (!availForm.start_time || !availForm.end_time) {
      setActionError('Start and end time are required.');
      return;
    }
    setAvailBusy(true);
    try {
      await api.post('/availability', {
        barber_id: profile.barber_id,
        date: availForm.date,
        start_time: availForm.start_time,
        end_time: availForm.end_time,
      });
      setNotice('Availability added.');
      setAvailForm({ date: today, start_time: '', end_time: '' });
      await fetchAll();
    } catch (err) {
      setActionError(err.message || 'Could not add availability.');
    } finally {
      setAvailBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-8"><LoadingState message="Loading dashboard..." /></main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">Barber Dashboard</h1>
            <p className="text-slate-500 mt-1">
              {profile ? (
                <>
                  {profile.name}
                  {profile.specialization ? ` · ${profile.specialization}` : ''}
                  {' · '}
                  <span className="capitalize">{profile.availability_status}</span>
                  {' · '}
                  {displayDate()}
                </>
              ) : (
                displayDate()
              )}
            </p>
          </div>
          <span className={`flex items-center gap-2 text-xs font-medium ${connected ? 'text-green-600' : 'text-slate-400'}`}>
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-slate-300'}`}></span>
            {connected ? 'Live updates' : 'Live updates temporarily unavailable'}
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

        {!profile && !error && (
          <div className="bg-white rounded-xl border border-slate-200 mb-6">
            <EmptyState title="No barber profile linked" message="Your account is not linked to a barber profile yet. Contact your administrator." />
          </div>
        )}

        {/* Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {[
            { label: "Today's Appointments", value: todaysAppointments.length },
            { label: 'Waiting Customers', value: waiting.length },
            { label: 'Currently Serving', value: serving ? `#${serving.queue_position}` : '—' },
            { label: 'Completed Today', value: completedToday },
          ].map((c) => (
            <div key={c.label} className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
              <p className="text-slate-500 text-sm">{c.label}</p>
              <p className="text-3xl font-bold text-slate-800 mt-1">{c.value}</p>
            </div>
          ))}
        </div>

        {/* Current customer */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Currently Serving</h2>
          {serving ? (
            (() => {
              const { appt, service } = entryDetails(serving);
              return <CurrentServing entry={serving} appt={appt} service={service} />;
            })()
          ) : (
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
              <p className="text-slate-500 flex-1">No customer currently being served.</p>
              <ActionButton onClick={serveNext} busy={pending.next} disabled={!profile || waiting.length === 0}>
                Serve Next Customer
              </ActionButton>
            </div>
          )}
        </div>

        {/* Live queue */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Live Queue</h2>
          {queue.length === 0 ? (
            <EmptyState title="No customers are currently waiting." />
          ) : (
            <div className="space-y-3">
              {queue.map((q) => {
                const { appt, service } = entryDetails(q);
                return (
                  <QueueRow
                    key={q.queue_id}
                    entry={q}
                    appt={appt}
                    service={service}
                    pending={pending}
                    hasActive={Boolean(serving)}
                    onServe={() => serveEntry(q.queue_id)}
                    onComplete={() => completeEntry(q.queue_id)}
                    onSkip={() => skipEntry(q.queue_id)}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* Today's appointments */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-4">Today&apos;s Appointments</h2>
          {todaysAppointments.length === 0 ? (
            <EmptyState title="No appointments scheduled for today." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-100">
                    <th className="py-2 pr-4 font-medium">Time</th>
                    <th className="py-2 pr-4 font-medium">Customer</th>
                    <th className="py-2 pr-4 font-medium">Service</th>
                    <th className="py-2 pr-4 font-medium">Duration</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 font-medium">Queue</th>
                  </tr>
                </thead>
                <tbody>
                  {todaysAppointments.map((a) => {
                    const svc = serviceOf(a.service_id);
                    const q = queue.find((x) => x.appointment_id === a.appointment_id);
                    return (
                      <tr key={a.appointment_id} className="border-b border-slate-50">
                        <td className="py-2 pr-4 font-medium text-slate-800">
                          {fmtTime(a.start_time)}{a.end_time ? ` – ${fmtTime(a.end_time)}` : ''}
                        </td>
                        <td className="py-2 pr-4 text-slate-600">Appt #{a.appointment_id}</td>
                        <td className="py-2 pr-4 text-slate-600">{svc?.service_name || '—'}</td>
                        <td className="py-2 pr-4 text-slate-600">{svc?.duration_minutes != null ? `${svc.duration_minutes} min` : '—'}</td>
                        <td className="py-2 pr-4">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusStyle(a.status)}`}>
                            {prettyStatus(a.status)}
                          </span>
                        </td>
                        <td className="py-2 text-slate-600">{q ? `#${q.queue_position}` : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Availability */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          <h2 className="text-lg font-semibold text-slate-800 mb-1">Availability</h2>
          <p className="text-slate-500 text-sm mb-4">Your working windows. Toggle a window or add a new one.</p>
          {availability.length === 0 ? (
            <p className="text-slate-500 text-sm mb-4">No availability windows for {fmtDate(today)}.</p>
          ) : (
            <div className="space-y-2 mb-4">
              {availability.map((v) => (
                <div key={v.availability_id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
                  <span className="text-sm font-medium text-slate-800">
                    {fmtDate(v.date)} · {fmtTime(v.start_time)} – {fmtTime(v.end_time)}
                  </span>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${statusStyle(v.status)}`}>
                    {v.status}
                  </span>
                  <button
                    onClick={() => toggleAvailability(v)}
                    disabled={pending[`avail-${v.availability_id}`]}
                    className="ml-auto text-sm text-blue-600 hover:text-blue-800 font-medium disabled:opacity-50"
                  >
                    {pending[`avail-${v.availability_id}`] ? 'Saving...' : 'Toggle'}
                  </button>
                </div>
              ))}
            </div>
          )}
          <form onSubmit={createAvailability} className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            <input type="date" value={availForm.date} min={today} onChange={(e) => setAvailForm({ ...availForm, date: e.target.value })}
              className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            <input type="time" value={availForm.start_time} onChange={(e) => setAvailForm({ ...availForm, start_time: e.target.value })}
              className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            <input type="time" value={availForm.end_time} onChange={(e) => setAvailForm({ ...availForm, end_time: e.target.value })}
              className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            <button type="submit" disabled={availBusy || !profile}
              className="col-span-2 sm:col-span-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition">
              {availBusy ? 'Adding...' : 'Add Window'}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

function CurrentServing({ entry, appt, service }) {
  return (
    <div className="bg-gradient-to-r from-green-600 to-green-700 rounded-xl p-6 text-white">
      <p className="text-green-200 text-sm mb-1">Now serving · Queue #{entry.queue_position}</p>
      <p className="text-2xl font-bold">
        {service?.service_name || 'Service'}
      </p>
      <p className="text-green-100 text-sm mt-1">
        Appt #{entry.appointment_id}
        {appt.start_time ? ` · ${fmtTime(appt.start_time)}${appt.end_time ? ` – ${fmtTime(appt.end_time)}` : ''}` : ''}
        {service?.duration_minutes != null ? ` · ${service.duration_minutes} min` : ''}
      </p>
      <span className="inline-block mt-3 px-3 py-1 rounded-full text-xs font-medium bg-white/20 capitalize">
        {prettyStatus(entry.status)}
      </span>
    </div>
  );
}

function QueueRow({ entry, appt, service, pending, hasActive, onServe, onComplete, onSkip }) {
  const status = String(entry.status).toLowerCase();
  const isWaiting = status === 'waiting';
  const isServing = status === 'serving' || status === 'in_progress';
  const terminal = TERMINAL_QUEUE.has(status) || (!isWaiting && !isServing);

  return (
    <div className="flex flex-wrap items-center gap-3 p-4 bg-slate-50 rounded-xl">
      <div className="w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold shrink-0">
        {entry.queue_position}
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-slate-800">
          {service?.service_name || 'Service'}
          <span className="text-slate-500 font-normal"> · Appt #{entry.appointment_id}</span>
        </p>
        <p className="text-sm text-slate-500">
          {appt.start_time ? `${fmtTime(appt.start_time)}${appt.end_time ? ` – ${fmtTime(appt.end_time)}` : ''} · ` : ''}
          {service?.duration_minutes != null ? `${service.duration_minutes} min · ` : ''}
          {entry.estimated_wait_minutes != null ? `~${entry.estimated_wait_minutes} min wait` : 'Calculating...'}
        </p>
        <div className="flex items-center gap-2 mt-1">
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusStyle(entry.status)}`}>
            {prettyStatus(entry.status)}
          </span>
          {entry.confidence && <ConfidenceBadge level={entry.confidence} />}
        </div>
      </div>
      {!terminal && (
        <div className="flex gap-2">
          {isWaiting && (
            <ActionButton onClick={onServe} busy={pending[`serve-${entry.queue_id}`]} disabled={hasActive} title={hasActive ? 'Finish the current customer first' : 'Start serving'}>
              Serve
            </ActionButton>
          )}
          {isServing && (
            <ActionButton onClick={onComplete} busy={pending[`complete-${entry.queue_id}`]} tone="success">
              Complete
            </ActionButton>
          )}
          {isWaiting && (
            <ActionButton onClick={onSkip} busy={pending[`skip-${entry.queue_id}`]} tone="danger">
              Skip
            </ActionButton>
          )}
        </div>
      )}
    </div>
  );
}
