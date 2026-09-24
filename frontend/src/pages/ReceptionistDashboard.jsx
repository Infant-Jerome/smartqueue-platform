import { useState, useEffect, useCallback, useMemo } from 'react';
import { Play, Check, Users, CalendarDays, Activity, Clock } from 'lucide-react';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { LoadingState, EmptyState, ErrorState } from '../components/States';
import { ConfidenceBadge } from '../components/QueueStatusCard';
import { fmtTime } from '../utils/format';
import { useQueueSocket } from '../hooks/useQueueSocket';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import StatusBadge from '../components/ui/StatusBadge';
import StatCard from '../components/ui/StatCard';
import PageHeader from '../components/ui/PageHeader';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import Field from '../components/ui/Field';
import Select from '../components/ui/Select';

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function displayDate() {
  return new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

const FILTERS = ['All', 'Waiting', 'Serving', 'Completed', 'Cancelled', 'No Show'];
const FILTER_STATUS = { Waiting: 'waiting', Serving: 'serving', Completed: 'completed', Cancelled: 'cancelled', 'No Show': 'no_show' };

/**
 * Receptionist / staff operational dashboard (Phase 9 Step 7 redesign —
 * presentation only). Salon-scoped overview using only staff-authorized
 * endpoints. Backend owns queue state, SAWTE estimates and RBAC.
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
  const [skipTarget, setSkipTarget] = useState(null);
  const [cancelTarget, setCancelTarget] = useState(null);

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

  const sortedQueue = useMemo(
    () => [...queue].sort((a, b) => a.queue_position - b.queue_position),
    [queue]
  );

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
        <PageHeader
          title="Reception Desk"
          description={`${displayDate()}${user?.name ? ` · ${user.name}` : ''} · Manage today's queue and appointments.`}
          actions={
            <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${connected ? 'text-[var(--sq-success)]' : 'text-[var(--sq-text-subtle)]'}`}>
              <span className="relative flex h-2 w-2" aria-hidden="true">
                {connected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--sq-success)] opacity-60" />
                )}
                <span className={`relative inline-flex rounded-full h-2 w-2 ${connected ? 'bg-[var(--sq-success)]' : 'bg-[var(--sq-border)]'}`} />
              </span>
              {connected ? 'Live' : 'Live updates temporarily unavailable'}
            </span>
          }
        />

        {error && (
          <div className="mb-4"><ErrorState message={error} onRetry={fetchAll} /></div>
        )}
        {actionError && (
          <div className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{actionError}</div>
        )}
        {notice && (
          <div className="mb-4 p-3 bg-[var(--sq-success-soft)] border border-[#bbf7d0] rounded-[var(--sq-radius-lg)] text-[var(--sq-success)] text-sm">{notice}</div>
        )}

        {/* Compact operational summary */}
        <div className="grid grid-cols-3 md:grid-cols-5 gap-3 mb-4">
          <StatCard title="Today" value={todaysAppointments.length} icon={<CalendarDays size={18} aria-hidden="true" />} />
          <StatCard title="Waiting" value={waitingCount} icon={<Users size={18} aria-hidden="true" />} />
          <StatCard title="Serving" value={servingCount} icon={<Activity size={18} aria-hidden="true" />} />
          <StatCard title="Done" value={completedCount} icon={<Check size={18} aria-hidden="true" />} />
          <StatCard title="Cancel/No-show" value={cancelledCount + noShowCount} icon={<Clock size={18} aria-hidden="true" />} />
        </div>

        {/* P0 — Live queue control panel */}
        <Card className="mb-4">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <h2 className="sq-h2 mr-auto">Live Queue</h2>
            <Field>
              <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status" className="!w-auto !min-h-0 py-1.5">
                {FILTERS.map((f) => <option key={f} value={f}>{f}</option>)}
              </Select>
            </Field>
            <Field>
              <Select value={barberFilter} onChange={(e) => setBarberFilter(e.target.value)} aria-label="Filter by barber" className="!w-auto !min-h-0 py-1.5">
                <option value="All">All barbers</option>
                {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
              </Select>
            </Field>
          </div>

          {servingEntries.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3" aria-label="Currently serving">
              {servingEntries.map((q) => {
                const barb = barberOf(q.barber_id);
                return (
                  <span key={q.queue_id} className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--sq-success-soft)] text-[var(--sq-success)] text-sm font-semibold">
                    <span className="relative flex h-2 w-2" aria-hidden="true">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--sq-success)] opacity-60" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--sq-success)]" />
                    </span>
                    <span className="sq-tnum">#{q.queue_position}</span> {barb?.name || `Barber #${q.barber_id}`}
                    <button
                      onClick={() => completeEntry(q.queue_id)}
                      disabled={pending[`complete-${q.queue_id}`]}
                      className="underline underline-offset-2 hover:no-underline disabled:opacity-50 font-medium"
                    >
                      {pending[`complete-${q.queue_id}`] ? '…' : 'Complete'}
                    </button>
                  </span>
                );
              })}
            </div>
          )}

          {sortedQueue.length === 0 ? (
            <EmptyState title="Queue is clear." message="New appointments will appear here." />
          ) : (
            <div className="space-y-2">
              {sortedQueue.map((q) => {
                const st = String(q.status).toLowerCase();
                const appt = apptById[q.appointment_id] || {};
                const svc = appt.service_id != null ? serviceOf(appt.service_id) : undefined;
                const barb = barberOf(q.barber_id);
                const serving = st === 'serving' || st === 'in_progress';
                const waiting = st === 'waiting';
                return (
                  <div
                    key={q.queue_id}
                    className={`flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 rounded-[var(--sq-radius-lg)] border-l-4 ${
                      serving
                        ? 'bg-[var(--sq-success-soft)]/40 border border-[var(--sq-border)] border-l-[var(--sq-success)]'
                        : 'bg-[var(--sq-surface-muted)] border border-transparent border-l-[var(--sq-border)]'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <span className="flex w-9 h-9 rounded-full bg-[var(--sq-primary)] text-white items-center justify-center font-bold sq-tnum shrink-0" aria-hidden="true">
                        {q.queue_position}
                      </span>
                      <div className="min-w-0">
                        <p className="font-semibold text-sm truncate">
                          Appt #{q.appointment_id} · {barb?.name || `Barber #${q.barber_id}`} · {svc?.service_name || 'Service'}
                        </p>
                        <p className="text-xs text-[var(--sq-text-muted)] sq-tnum">
                          {appt.start_time ? `${fmtTime(appt.start_time)} · ` : ''}
                          {q.estimated_wait_minutes != null ? `~${q.estimated_wait_minutes} min` : 'Calculating…'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 ml-12 sm:ml-0">
                      <StatusBadge status={q.status} />
                      {q.confidence && <ConfidenceBadge level={q.confidence} />}
                    </div>
                    <div className="flex gap-1.5 ml-12 sm:ml-0">
                      {waiting && (
                        <Button size="sm" onClick={() => serveEntry(q.queue_id)} loading={pending[`serve-${q.queue_id}`]} icon={<Play size={13} aria-hidden="true" />}>
                          Serve
                        </Button>
                      )}
                      {serving && (
                        <Button size="sm" tone="success" onClick={() => completeEntry(q.queue_id)} loading={pending[`complete-${q.queue_id}`]} icon={<Check size={13} aria-hidden="true" />}>
                          Done
                        </Button>
                      )}
                      {waiting && (
                        <Button size="sm" tone="danger" onClick={() => setSkipTarget(q)} loading={pending[`skip-${q.queue_id}`]}>
                          Skip
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <div className="grid lg:grid-cols-5 gap-4 items-start">
          {/* P1 — appointments */}
          <Card className="lg:col-span-3">
            <h2 className="sq-h2 mb-3">Today&apos;s Appointments</h2>
            {todaysAppointments.length === 0 ? (
              <EmptyState title="No appointments scheduled for today." />
            ) : (
              <div className="space-y-2">
                {todaysAppointments.map((a) => {
                  const svc = a.service_id != null ? serviceOf(a.service_id) : undefined;
                  const barb = barberOf(a.barber_id);
                  const st = String(a.status || '').toLowerCase();
                  const terminal = ['completed', 'cancelled', 'no_show'].includes(st);
                  const q = queue.find((x) => x.appointment_id === a.appointment_id);
                  return (
                    <div key={a.appointment_id} className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
                      <span className="font-semibold sq-tnum text-sm whitespace-nowrap">
                        {fmtTime(a.start_time)}{a.end_time ? `–${fmtTime(a.end_time)}` : ''}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">
                          #{a.appointment_id} · {barb?.name || `#${a.barber_id}`} · {svc?.service_name || '—'}
                        </p>
                        <p className="text-xs text-[var(--sq-text-muted)]">
                          {svc?.duration_minutes != null ? `${svc.duration_minutes} min` : ''}
                          {q ? ` · Q#${q.queue_position}` : ''}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <StatusBadge status={a.status} />
                        {!terminal && (
                          <>
                            {st === 'booked' && (
                              <Button size="sm" tone="secondary" loading={pending[`confirm-${a.appointment_id}`]}
                                onClick={() => runAction(`confirm-${a.appointment_id}`, () => api.put(`/appointments/${a.appointment_id}`, { status: 'confirmed' }), 'Appointment confirmed.')}>
                                Confirm
                              </Button>
                            )}
                            <Button size="sm" tone="danger" loading={pending[`cancel-${a.appointment_id}`]}
                              onClick={() => setCancelTarget(a)}>
                              Cancel
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* P2 — barber overview */}
          <Card className="lg:col-span-2">
            <h2 className="sq-h2 mb-3">Barbers</h2>
            {barbers.length === 0 ? (
              <EmptyState title="No barber data available." />
            ) : (
              <div className="space-y-3">
                {barbers.map((b) => {
                  const rows = queueForBarber(b.barber_id);
                  const w = rows.filter((q) => String(q.status).toLowerCase() === 'waiting').length;
                  const s = rows.filter((q) => ['serving', 'in_progress'].includes(String(q.status).toLowerCase())).length;
                  const wins = availForBarber(b.barber_id);
                  return (
                    <div key={b.barber_id} className="border border-[var(--sq-border)] rounded-[var(--sq-radius-lg)] p-3">
                      <div className="flex items-center gap-2.5">
                        <span className="flex w-9 h-9 rounded-full bg-[var(--sq-primary-soft)] text-[var(--sq-primary)] items-center justify-center font-bold shrink-0" aria-hidden="true">
                          {(b.name || '?').charAt(0)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold text-sm truncate">{b.name}</p>
                          <p className="text-xs text-[var(--sq-text-muted)] truncate">
                            {b.specialization || 'General'} · <span className="capitalize">{b.availability_status}</span>
                          </p>
                        </div>
                        <span className="sq-caption sq-tnum text-[var(--sq-text-muted)] shrink-0" aria-label={`${w} waiting, ${s} serving`}>
                          {w}W · {s}S
                        </span>
                      </div>
                      <p className="text-xs text-[var(--sq-text-subtle)] mt-1.5">
                        {wins.length ? wins.map((x) => `${fmtTime(x.start_time)}–${fmtTime(x.end_time)}`).join(', ') : 'no windows listed'}
                      </p>
                      <Button size="sm" fullWidth className="mt-2" loading={pending[`next-${b.barber_id}`]}
                        onClick={() => serveNextFor(b.barber_id)}>
                        Serve Next
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </main>

      <ConfirmDialog
        open={Boolean(skipTarget)}
        title="Mark as no-show?"
        description={skipTarget ? `Queue #${skipTarget.queue_position} (Appt #${skipTarget.appointment_id}) will leave the waiting list.` : ''}
        confirmLabel="Mark no-show"
        danger
        loading={skipTarget ? pending[`skip-${skipTarget.queue_id}`] : false}
        onCancel={() => setSkipTarget(null)}
        onConfirm={() => {
          if (skipTarget) {
            skipEntry(skipTarget.queue_id);
            setSkipTarget(null);
          }
        }}
      />
      <ConfirmDialog
        open={Boolean(cancelTarget)}
        title="Cancel this appointment?"
        description={cancelTarget ? `Appointment #${cancelTarget.appointment_id} will be cancelled for the customer.` : ''}
        confirmLabel="Cancel appointment"
        danger
        loading={cancelTarget ? pending[`cancel-${cancelTarget.appointment_id}`] : false}
        onCancel={() => setCancelTarget(null)}
        onConfirm={() => {
          if (cancelTarget) {
            runAction(`cancel-${cancelTarget.appointment_id}`, () => api.delete(`/appointments/${cancelTarget.appointment_id}`), 'Appointment cancelled.');
            setCancelTarget(null);
          }
        }}
      />
    </div>
  );
}
