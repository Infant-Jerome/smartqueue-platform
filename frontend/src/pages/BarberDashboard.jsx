import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Play, Check, Clock, CalendarDays, Users, Activity,
  User, Scissors, Plus,
} from 'lucide-react';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { LoadingState, EmptyState, ErrorState } from '../components/States';
import { ConfidenceBadge } from '../components/QueueStatusCard';
import { fmtTime, fmtDate } from '../utils/format';
import { useQueueSocket } from '../hooks/useQueueSocket';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import StatusBadge from '../components/ui/StatusBadge';
import StatCard from '../components/ui/StatCard';
import PageHeader from '../components/ui/PageHeader';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import Field from '../components/ui/Field';
import Input from '../components/ui/Input';

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

function firstName(user) {
  const name = String(user?.name || '').trim();
  return name ? name.split(/\s+/)[0] : null;
}

const TERMINAL_QUEUE = new Set(['completed', 'cancelled', 'no_show']);

/**
 * Barber operational dashboard (Phase 9 Step 6 redesign — presentation only).
 * Same endpoints, same handlers, same data flow as before; backend owns
 * queue state, SAWTE estimates and RBAC.
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
  const [skipTarget, setSkipTarget] = useState(null);
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

  const waiting = useMemo(
    () => queue.filter((q) => String(q.status).toLowerCase() === 'waiting')
      .sort((a, b) => a.queue_position - b.queue_position),
    [queue]
  );
  const serving = queue.find((q) => ['serving', 'in_progress'].includes(String(q.status).toLowerCase())) || null;
  const nextUp = waiting[0] || null;
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
        <PageHeader
          title={`${greeting()}${firstName(user) ? `, ${firstName(user)}` : ''}`}
          description={
            profile
              ? `Here's your queue for today${profile.specialization ? ` · ${profile.specialization}` : ''}`
              : 'Here is your operational overview.'
          }
          actions={
            <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${connected ? 'text-[var(--sq-success)]' : 'text-[var(--sq-text-subtle)]'}`}>
              <span className="relative flex h-2 w-2" aria-hidden="true">
                {connected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--sq-success)] opacity-60" />
                )}
                <span className={`relative inline-flex rounded-full h-2 w-2 ${connected ? 'bg-[var(--sq-success)]' : 'bg-[var(--sq-border)]'}`} />
              </span>
              {connected ? 'Live updates' : 'Live updates temporarily unavailable'}
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

        {!profile && !error && (
          <Card className="mb-6">
            <EmptyState title="No barber profile linked" message="Your account is not linked to a barber profile yet. Contact your administrator." />
          </Card>
        )}

        <div className="grid lg:grid-cols-3 gap-4 items-start">
          {/* MAIN COLUMN — current customer, primary action, next, queue */}
          <div className="lg:col-span-2 space-y-4 min-w-0">
            <ServingHero
              serving={serving}
              entryDetails={entryDetails}
              pending={pending}
              canServeNext={Boolean(profile) && waiting.length > 0}
              onServeNext={serveNext}
              onComplete={() => serving && completeEntry(serving.queue_id)}
              onSkip={() => serving && setSkipTarget(serving)}
            />

            <NextUpCard
              nextUp={nextUp}
              entryDetails={entryDetails}
              pending={pending}
              hasActive={Boolean(serving)}
              onServe={() => nextUp && serveEntry(nextUp.queue_id)}
              onSkip={() => nextUp && setSkipTarget(nextUp)}
            />

            <Card>
              <div className="flex items-center justify-between mb-3">
                <h2 className="sq-h2">Live Queue</h2>
                <span className="sq-caption text-[var(--sq-text-subtle)] sq-tnum">
                  {waiting.length} waiting{serving ? ' · 1 serving' : ''}
                </span>
              </div>
              {queue.length === 0 ? (
                <EmptyState title="Queue is clear." message="No customers are currently waiting." />
              ) : (
                <div className="space-y-2">
                  {[...queue].sort((a, b) => a.queue_position - b.queue_position).map((q) => {
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
                        onSkip={() => setSkipTarget(q)}
                      />
                    );
                  })}
                </div>
              )}
            </Card>
          </div>

          {/* SECONDARY COLUMN — summary, availability */}
          <div className="space-y-4 min-w-0">
            <div className="grid grid-cols-2 lg:grid-cols-1 xl:grid-cols-2 gap-3">
              <StatCard title="Today" value={todaysAppointments.length} icon={<CalendarDays size={18} aria-hidden="true" />} description="appointments" />
              <StatCard title="Waiting" value={waiting.length} icon={<Users size={18} aria-hidden="true" />} description="customers" />
              <StatCard title="Serving" value={serving ? `#${serving.queue_position}` : '—'} icon={<Activity size={18} aria-hidden="true" />} />
              <StatCard title="Done" value={completedToday} icon={<Check size={18} aria-hidden="true" />} description="completed" />
            </div>

            <Card>
              <div className="flex items-center justify-between mb-3">
                <h2 className="sq-h2">Availability</h2>
                {profile && (
                  <span className="sq-caption capitalize text-[var(--sq-text-muted)]">
                    {profile.availability_status}
                  </span>
                )}
              </div>
              {availability.length === 0 ? (
                <p className="sq-body-sm text-[var(--sq-text-muted)] mb-3">No windows for {fmtDate(today)}.</p>
              ) : (
                <div className="space-y-2 mb-3">
                  {availability.map((v) => (
                    <div key={v.availability_id} className="flex items-center gap-2 p-2.5 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
                      <span className="text-sm font-medium sq-tnum">
                        {fmtTime(v.start_time)} – {fmtTime(v.end_time)}
                      </span>
                      <StatusBadge status={v.status} />
                      <button
                        onClick={() => toggleAvailability(v)}
                        disabled={pending[`avail-${v.availability_id}`]}
                        className="ml-auto text-sm text-[var(--sq-primary)] hover:underline font-medium disabled:opacity-50"
                      >
                        {pending[`avail-${v.availability_id}`] ? 'Saving...' : 'Toggle'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <form onSubmit={createAvailability} className="grid grid-cols-2 gap-2">
                <Field label="Date">
                  <Input type="date" value={availForm.date} min={today} onChange={(e) => setAvailForm({ ...availForm, date: e.target.value })} />
                </Field>
                <div className="grid grid-cols-2 gap-2 col-span-2 sm:col-span-1 lg:col-span-2 xl:col-span-1">
                  <Field label="Start">
                    <Input type="time" value={availForm.start_time} onChange={(e) => setAvailForm({ ...availForm, start_time: e.target.value })} />
                  </Field>
                  <Field label="End">
                    <Input type="time" value={availForm.end_time} onChange={(e) => setAvailForm({ ...availForm, end_time: e.target.value })} />
                  </Field>
                </div>
                <div className="col-span-2">
                  <Button type="submit" fullWidth loading={availBusy} disabled={!profile} icon={<Plus size={15} aria-hidden="true" />}>
                    Add Window
                  </Button>
                </div>
              </form>
            </Card>
          </div>
        </div>

        {/* BOTTOM — today's appointments */}
        <Card className="mt-4">
          <h2 className="sq-h2 mb-3">Today&apos;s Appointments</h2>
          {todaysAppointments.length === 0 ? (
            <EmptyState title="No appointments scheduled for today." />
          ) : (
            <div className="space-y-2">
              {todaysAppointments.map((a) => {
                const svc = serviceOf(a.service_id);
                const q = queue.find((x) => x.appointment_id === a.appointment_id);
                return (
                  <div key={a.appointment_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
                    <span className="font-semibold sq-tnum">
                      {fmtTime(a.start_time)}{a.end_time ? ` – ${fmtTime(a.end_time)}` : ''}
                    </span>
                    <span className="text-sm text-[var(--sq-text-muted)]">Appt #{a.appointment_id}</span>
                    <span className="text-sm font-medium">{svc?.service_name || 'Service'}</span>
                    <span className="text-sm text-[var(--sq-text-muted)] sq-tnum">
                      {svc?.duration_minutes != null ? `${svc.duration_minutes} min` : ''}
                    </span>
                    <span className="ml-auto flex items-center gap-2">
                      {q && <span className="sq-caption text-[var(--sq-text-subtle)] sq-tnum">Q#{q.queue_position}</span>}
                      <StatusBadge status={a.status} />
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </main>

      <ConfirmDialog
        open={Boolean(skipTarget)}
        title="Mark as no-show?"
        description={
          skipTarget
            ? `Queue #${skipTarget.queue_position} will leave the waiting list. This follows the normal backend transition.`
            : ''
        }
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
    </div>
  );
}

function ServingHero({ serving, entryDetails, pending, canServeNext, onServeNext, onComplete, onSkip }) {
  if (!serving) {
    return (
      <Card padding="lg">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex-1 min-w-0">
            <p className="sq-caption uppercase tracking-widest text-[var(--sq-text-subtle)]">Currently serving</p>
            <p className="sq-h1 mt-1">No customer right now</p>
            <p className="sq-body-sm text-[var(--sq-text-muted)] mt-1">Start the next waiting customer when you’re ready.</p>
          </div>
          <Button size="lg" onClick={onServeNext} loading={pending.next} disabled={!canServeNext} icon={<Play size={18} aria-hidden="true" />}>
            Serve Next Customer
          </Button>
        </div>
      </Card>
    );
  }

  const { appt, service } = entryDetails(serving);
  return (
    <Card padding="lg" className="border-l-4 border-l-[var(--sq-success)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="sq-caption uppercase tracking-widest text-[var(--sq-success)]">Now serving</p>
          <p className="sq-display sq-tnum mt-1">#{serving.queue_position}</p>
        </div>
        <StatusBadge status={serving.status} />
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-3 sq-body-sm text-[var(--sq-text-muted)]">
        <span className="inline-flex items-center gap-1.5">
          <Scissors size={15} aria-hidden="true" /> {service?.service_name || 'Service'}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <User size={15} aria-hidden="true" /> Appt #{serving.appointment_id}
        </span>
        {(appt.start_time || appt.end_time) && (
          <span className="inline-flex items-center gap-1.5 sq-tnum">
            <Clock size={15} aria-hidden="true" />
            {fmtTime(appt.start_time)}{appt.end_time ? ` – ${fmtTime(appt.end_time)}` : ''}
          </span>
        )}
        {service?.duration_minutes != null && (
          <span className="sq-tnum">{service.duration_minutes} min</span>
        )}
      </div>
      <div className="flex flex-col sm:flex-row gap-2 mt-5">
        <Button size="lg" tone="success" fullWidth onClick={onComplete} loading={pending[`complete-${serving.queue_id}`]} icon={<Check size={18} aria-hidden="true" />}>
          Complete Service
        </Button>
        <Button size="lg" tone="danger" onClick={onSkip} loading={pending[`skip-${serving.queue_id}`]}>
          Skip
        </Button>
      </div>
    </Card>
  );
}

function NextUpCard({ nextUp, entryDetails, pending, hasActive, onServe, onSkip }) {
  if (!nextUp) {
    return (
      <Card>
        <div className="flex items-center gap-3">
          <span className="flex w-10 h-10 rounded-[var(--sq-radius-lg)] bg-[var(--sq-surface-muted)] text-[var(--sq-text-subtle)] items-center justify-center shrink-0" aria-hidden="true">
            <Users size={18} />
          </span>
          <div>
            <p className="font-semibold">Queue is clear</p>
            <p className="sq-body-sm text-[var(--sq-text-muted)]">No customers waiting right now.</p>
          </div>
        </div>
      </Card>
    );
  }

  const { appt, service } = entryDetails(nextUp);
  return (
    <Card className="border-l-4 border-l-[var(--sq-accent)]">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex w-11 h-11 rounded-full bg-[var(--sq-accent-soft)] text-[var(--sq-accent)] items-center justify-center font-bold sq-tnum text-lg shrink-0" aria-hidden="true">
          {nextUp.queue_position}
        </span>
        <div className="min-w-0 flex-1">
          <p className="sq-caption uppercase tracking-widest text-[var(--sq-text-subtle)]">Next up</p>
          <p className="font-semibold truncate">
            {service?.service_name || 'Service'}
            <span className="font-normal text-[var(--sq-text-muted)]"> · Appt #{nextUp.appointment_id}</span>
          </p>
          <p className="sq-body-sm text-[var(--sq-text-muted)] sq-tnum">
            {appt.start_time ? `${fmtTime(appt.start_time)} · ` : ''}
            {nextUp.estimated_wait_minutes != null ? `~${nextUp.estimated_wait_minutes} min wait` : 'Calculating…'}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={onServe} loading={pending[`serve-${nextUp.queue_id}`]} disabled={hasActive}
            icon={<Play size={14} aria-hidden="true" />}>
            Serve
          </Button>
          <Button size="sm" tone="danger" onClick={onSkip} loading={pending[`skip-${nextUp.queue_id}`]}>
            Skip
          </Button>
        </div>
      </div>
    </Card>
  );
}

function QueueRow({ entry, appt, service, pending, hasActive, onServe, onComplete, onSkip }) {
  const status = String(entry.status).toLowerCase();
  const isWaiting = status === 'waiting';
  const isServing = status === 'serving' || status === 'in_progress';
  const terminal = TERMINAL_QUEUE.has(status) || (!isWaiting && !isServing);

  return (
    <div className="flex flex-wrap items-center gap-3 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)]">
      <span className="flex w-9 h-9 rounded-full bg-[var(--sq-primary)] text-white items-center justify-center font-bold sq-tnum shrink-0" aria-hidden="true">
        {entry.queue_position}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-sm truncate">
          {service?.service_name || 'Service'}
          <span className="font-normal text-[var(--sq-text-muted)]"> · Appt #{entry.appointment_id}</span>
        </p>
        <p className="text-xs text-[var(--sq-text-muted)] sq-tnum">
          {appt.start_time ? `${fmtTime(appt.start_time)} · ` : ''}
          {entry.estimated_wait_minutes != null ? `~${entry.estimated_wait_minutes} min` : 'Calculating…'}
        </p>
        <div className="flex items-center gap-2 mt-1">
          <StatusBadge status={entry.status} />
          {entry.confidence && <ConfidenceBadge level={entry.confidence} />}
        </div>
      </div>
      {!terminal && (
        <div className="flex gap-1.5">
          {isWaiting && (
            <Button size="sm" onClick={onServe} loading={pending[`serve-${entry.queue_id}`]} disabled={hasActive}
              title={hasActive ? 'Finish the current customer first' : 'Start serving'}>
              Serve
            </Button>
          )}
          {isServing && (
            <Button size="sm" tone="success" onClick={onComplete} loading={pending[`complete-${entry.queue_id}`]}>
              Complete
            </Button>
          )}
          {isWaiting && (
            <Button size="sm" tone="danger" onClick={onSkip} loading={pending[`skip-${entry.queue_id}`]}>
              Skip
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
