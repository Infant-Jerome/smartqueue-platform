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

const VALID_ROLES = ['customer', 'barber', 'receptionist', 'staff', 'admin'];

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

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
      <h2 className="text-lg font-semibold text-slate-800 mb-4">{title}</h2>
      {children}
    </div>
  );
}

/**
 * Admin system-management dashboard (Frontend Phase 5).
 * Uses only verified admin-authorized endpoints. No user-list endpoint
 * exists in the backend, so user management is lookup-by-ID + role update.
 * Backend owns all state, SAWTE values and RBAC.
 */
export default function Admin() {
  const { user } = useAuth();
  const today = useMemo(() => todayStr(), []);
  const [tab, setTab] = useState('overview');

  const [appointments, setAppointments] = useState([]);
  const [queue, setQueue] = useState([]);
  const [barbers, setBarbers] = useState([]);
  const [services, setServices] = useState([]);
  const [availability, setAvailability] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState({});

  const [apptStatusFilter, setApptStatusFilter] = useState('All');
  const [apptBarberFilter, setApptBarberFilter] = useState('All');
  const [queueStatusFilter, setQueueStatusFilter] = useState('All');
  const [queueBarberFilter, setQueueBarberFilter] = useState('All');

  const [lookupId, setLookupId] = useState('');
  const [lookupUser, setLookupUser] = useState(null);
  const [lookupError, setLookupError] = useState('');
  const [newRole, setNewRole] = useState('');
  const [confirmSelfDemote, setConfirmSelfDemote] = useState(false);

  const [svcForm, setSvcForm] = useState({ service_name: '', description: '', duration_minutes: '', price: '', status: 'active' });
  const [editingSvc, setEditingSvc] = useState(null);
  const [barberForm, setBarberForm] = useState({ name: '', specialization: '', phone: '', experience_years: '', availability_status: 'available' });
  const [editingBarber, setEditingBarber] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [availForm, setAvailForm] = useState({ barber_id: '', date: todayStr(), start_time: '', end_time: '' });

  const serviceOf = useCallback((id) => services.find((s) => s.service_id === id), [services]);
  const barberOf = useCallback((id) => barbers.find((b) => b.barber_id === id), [barbers]);

  const salonId = useMemo(() => {
    const ids = [...barbers.map((b) => b.salon_id), ...appointments.map((a) => a.salon_id)].filter((v) => v != null);
    return ids.length ? [...new Set(ids)][0] : null;
  }, [barbers, appointments]);

  const fetchAll = useCallback(async () => {
    setError('');
    try {
      const [aRes, qRes, bRes, sRes, vRes, nRes] = await Promise.all([
        api.get('/appointments'),
        api.get('/queue').catch(() => ({ data: [] })),
        api.get('/barbers').catch(() => ({ data: [] })),
        api.get('/services').catch(() => ({ data: [] })),
        api.get('/availability', { params: { date: today } }).catch(() => ({ data: [] })),
        api.get('/notifications').catch(() => ({ data: [] })),
      ]);
      setAppointments(Array.isArray(aRes.data) ? aRes.data : []);
      setQueue(Array.isArray(qRes.data) ? qRes.data : []);
      setBarbers(Array.isArray(bRes.data) ? bRes.data : []);
      setServices(Array.isArray(sRes.data) ? sRes.data : []);
      setAvailability(Array.isArray(vRes.data) ? vRes.data : []);
      setNotifications(Array.isArray(nRes.data) ? nRes.data : []);
    } catch (err) {
      setError(err.message || 'Unable to load dashboard data.');
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const { connected } = useQueueSocket({
    salonId,
    date: today,
    enabled: Boolean(salonId),
    onEvent: () => fetchAll(),
  });

  const runAction = async (key, fn, successMsg) => {
    setPending((p) => ({ ...p, [key]: true }));
    setActionError('');
    setNotice('');
    try {
      await fn();
      setNotice(successMsg);
      await fetchAll();
      return true;
    } catch (err) {
      setActionError(err.message || 'Action could not be completed.');
      return false;
    } finally {
      setPending((p) => ({ ...p, [key]: false }));
    }
  };

  const todaysAppointments = useMemo(
    () =>
      appointments
        .filter((a) => String(a.appointment_date).slice(0, 10) === today)
        .sort((x, y) => String(x.start_time).localeCompare(String(y.start_time))),
    [appointments, today]
  );

  const filteredQueue = useMemo(() => {
    let rows = [...queue].sort((a, b) => a.queue_position - b.queue_position);
    if (queueStatusFilter !== 'All') rows = rows.filter((q) => String(q.status).toLowerCase() === queueStatusFilter.toLowerCase().replace(' ', '_').replace('no_show', 'no_show'));
    if (queueBarberFilter !== 'All') rows = rows.filter((q) => q.barber_id === Number(queueBarberFilter));
    return rows;
  }, [queue, queueStatusFilter, queueBarberFilter]);

  const lookup = async (e) => {
    e?.preventDefault();
    setLookupError('');
    setLookupUser(null);
    setNewRole('');
    setConfirmSelfDemote(false);
    if (!lookupId) return;
    try {
      const res = await api.get(`/users/${lookupId}`);
      setLookupUser(res.data);
      setNewRole(res.data.role);
    } catch (err) {
      setLookupError(err.message || 'User not found.');
    }
  };

  const applyRole = async () => {
    if (!lookupUser || !newRole || newRole === lookupUser.role) return;
    const isSelf = lookupUser.user_id === user?.user_id;
    if (isSelf && newRole !== 'admin' && !confirmSelfDemote) {
      setConfirmSelfDemote(true);
      return;
    }
    const ok = await runAction('role', () => api.patch(`/users/${lookupUser.user_id}/role`, { role: newRole }), 'Role updated.');
    if (ok) {
      const res = await api.get(`/users/${lookupUser.user_id}`).catch(() => null);
      if (res) {
        setLookupUser(res.data);
        setNewRole(res.data.role);
      }
      setConfirmSelfDemote(false);
    }
  };

  const submitService = async (e) => {
    e.preventDefault();
    const payload = {
      service_name: svcForm.service_name.trim(),
      duration_minutes: Number(svcForm.duration_minutes),
      price: Number(svcForm.price),
      ...(svcForm.description.trim() ? { description: svcForm.description.trim() } : {}),
      status: svcForm.status,
    };
    if (editingSvc) {
      await runAction('svc-save', () => api.put(`/services/${editingSvc}`, payload), 'Service updated.');
    } else {
      await runAction('svc-save', () => api.post('/services', payload), 'Service created.');
    }
    setEditingSvc(null);
    setSvcForm({ service_name: '', description: '', duration_minutes: '', price: '', status: 'active' });
  };

  const submitBarber = async (e) => {
    e.preventDefault();
    const payload = {
      name: barberForm.name.trim(),
      ...(barberForm.specialization.trim() ? { specialization: barberForm.specialization.trim() } : {}),
      ...(barberForm.phone.trim() ? { phone: barberForm.phone.trim() } : {}),
      ...(barberForm.experience_years !== '' ? { experience_years: Number(barberForm.experience_years) } : {}),
      availability_status: barberForm.availability_status,
    };
    if (editingBarber) {
      await runAction('barber-save', () => api.put(`/barbers/${editingBarber}`, payload), 'Barber updated.');
    } else {
      await runAction('barber-save', () => api.post('/barbers', payload), 'Barber created.');
    }
    setEditingBarber(null);
    setBarberForm({ name: '', specialization: '', phone: '', experience_years: '', availability_status: 'available' });
  };

  const submitAvailability = async (e) => {
    e.preventDefault();
    await runAction(
      'avail-save',
      () => api.post('/availability', {
        barber_id: Number(availForm.barber_id),
        date: availForm.date,
        start_time: availForm.start_time,
        end_time: availForm.end_time,
      }),
      'Availability added.'
    );
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-8"><LoadingState message="Loading admin dashboard..." /></main>
      </div>
    );
  }

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'queue', label: 'Queue' },
    { id: 'appointments', label: 'Appointments' },
    { id: 'users', label: 'Users' },
    { id: 'barbers', label: 'Barbers' },
    { id: 'services', label: 'Services' },
    { id: 'availability', label: 'Availability' },
    { id: 'notifications', label: 'Notifications' },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">Admin Dashboard</h1>
            <p className="text-slate-500 mt-1">{displayDate()}{user?.name ? ` · ${user.name}` : ''}</p>
          </div>
          <span className={`flex items-center gap-2 text-xs font-medium ${connected ? 'text-green-600' : 'text-slate-400'}`}>
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-slate-300'}`}></span>
            {connected ? 'Live' : 'Live updates temporarily unavailable'}
          </span>
        </div>

        {error && <div className="mb-4"><ErrorState message={error} onRetry={fetchAll} /></div>}
        {actionError && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">{actionError}</div>}
        {notice && <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">{notice}</div>}

        <div className="flex gap-2 mb-6 overflow-x-auto">
          {tabs.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition ${
                tab === t.id ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}>{t.label}</button>
          ))}
        </div>

        {tab === 'overview' && (
          <OverviewTab
            todaysAppointments={todaysAppointments}
            queue={queue}
            barbers={barbers}
            services={services}
            notifications={notifications}
          />
        )}

        {tab === 'queue' && (
          <Section title="Queue Overview">
            <div className="flex flex-wrap gap-2 mb-4">
              <select value={queueStatusFilter} onChange={(e) => setQueueStatusFilter(e.target.value)} className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
                {['All', 'Waiting', 'Serving', 'Completed', 'Cancelled', 'No Show'].map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              <select value={queueBarberFilter} onChange={(e) => setQueueBarberFilter(e.target.value)} className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
                <option value="All">All barbers</option>
                {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
              </select>
            </div>
            {filteredQueue.length === 0 ? (
              <EmptyState title="No queue entries match." />
            ) : (
              <div className="space-y-2">
                {filteredQueue.map((q) => {
                  const st = String(q.status).toLowerCase();
                  return (
                    <div key={q.queue_id} className="flex flex-wrap items-center gap-3 p-3 bg-slate-50 rounded-xl">
                      <div className="w-9 h-9 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold shrink-0">{q.queue_position}</div>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-slate-800 text-sm">
                          Appt #{q.appointment_id} · {barberOf(q.barber_id)?.name || `Barber #${q.barber_id}`}
                        </p>
                        <p className="text-xs text-slate-500">
                          {q.estimated_wait_minutes != null ? `~${q.estimated_wait_minutes} min wait` : 'Calculating...'}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusStyle(q.status)}`}>{prettyStatus(q.status)}</span>
                          {q.confidence && <ConfidenceBadge level={q.confidence} />}
                        </div>
                      </div>
                      <div className="flex gap-1.5">
                        {st === 'waiting' && <ActionButton busy={pending[`serve-${q.queue_id}`]} onClick={() => runAction(`serve-${q.queue_id}`, () => api.post(`/queue/${q.queue_id}/serve`), 'Customer is being served.')}>Serve</ActionButton>}
                        {(st === 'serving' || st === 'in_progress') && <ActionButton busy={pending[`complete-${q.queue_id}`]} tone="success" onClick={() => runAction(`complete-${q.queue_id}`, () => api.post(`/queue/${q.queue_id}/complete`), 'Service completed.')}>Complete</ActionButton>}
                        {st === 'waiting' && <ActionButton busy={pending[`skip-${q.queue_id}`]} tone="danger" onClick={() => runAction(`skip-${q.queue_id}`, () => api.post(`/queue/${q.queue_id}/skip`), 'Marked as no-show.')}>Skip</ActionButton>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="mt-4">
              <h3 className="text-sm font-semibold text-slate-700 mb-2">Serve next per barber</h3>
              <div className="flex flex-wrap gap-2">
                {barbers.map((b) => (
                  <button key={b.barber_id} disabled={pending[`next-${b.barber_id}`]}
                    onClick={() => runAction(`next-${b.barber_id}`, () => api.post('/queue/serve-next', { barber_id: b.barber_id }), `Serving next for ${b.name}.`)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 disabled:opacity-50">
                    {pending[`next-${b.barber_id}`] ? '...' : `Next: ${b.name}`}
                  </button>
                ))}
              </div>
            </div>
          </Section>
        )}

        {tab === 'appointments' && (
          <Section title="Appointments">
            <div className="flex flex-wrap gap-2 mb-4">
              <select value={apptStatusFilter} onChange={(e) => setApptStatusFilter(e.target.value)} className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
                {['All', 'Booked', 'Confirmed', 'Waiting', 'In Progress', 'Completed', 'Cancelled', 'No Show'].map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              <select value={apptBarberFilter} onChange={(e) => setApptBarberFilter(e.target.value)} className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
                <option value="All">All barbers</option>
                {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
              </select>
            </div>
            {(() => {
              let rows = [...todaysAppointments];
              if (apptStatusFilter !== 'All') rows = rows.filter((a) => String(a.status).toLowerCase() === apptStatusFilter.toLowerCase().replace(' ', '_'));
              if (apptBarberFilter !== 'All') rows = rows.filter((a) => a.barber_id === Number(apptBarberFilter));
              if (!rows.length) return <EmptyState title="No appointments match." />;
              return (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-100">
                        <th className="py-2 pr-4 font-medium">Time</th>
                        <th className="py-2 pr-4 font-medium">Appt</th>
                        <th className="py-2 pr-4 font-medium">Barber</th>
                        <th className="py-2 pr-4 font-medium">Service</th>
                        <th className="py-2 pr-4 font-medium">Status</th>
                        <th className="py-2 font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((a) => {
                        const st = String(a.status || '').toLowerCase();
                        const terminal = ['completed', 'cancelled', 'no_show'].includes(st);
                        return (
                          <tr key={a.appointment_id} className="border-b border-slate-50">
                            <td className="py-2 pr-4 font-medium whitespace-nowrap">{fmtTime(a.start_time)}{a.end_time ? ` – ${fmtTime(a.end_time)}` : ''}</td>
                            <td className="py-2 pr-4">#{a.appointment_id}</td>
                            <td className="py-2 pr-4">{barberOf(a.barber_id)?.name || `#${a.barber_id}`}</td>
                            <td className="py-2 pr-4">{serviceOf(a.service_id)?.service_name || '—'}</td>
                            <td className="py-2 pr-4"><span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusStyle(a.status)}`}>{prettyStatus(a.status)}</span></td>
                            <td className="py-2">
                              {!terminal && (
                                <div className="flex gap-1.5">
                                  <ActionButton busy={pending[`cancel-${a.appointment_id}`]} tone="danger" onClick={() => runAction(`cancel-${a.appointment_id}`, () => api.delete(`/appointments/${a.appointment_id}`), 'Appointment cancelled.')}>Cancel</ActionButton>
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              );
            })()}
          </Section>
        )}

        {tab === 'users' && (
          <Section title="User Management">
            <p className="text-sm text-slate-500 mb-4">
              The backend exposes user lookup by ID (no user-list endpoint), plus admin role assignment.
            </p>
            <form onSubmit={lookup} className="flex gap-2 mb-4">
              <input value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder="User ID (e.g. 1)"
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500 w-48" />
              <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">Look up</button>
            </form>
            {lookupError && <p className="text-sm text-red-600 mb-4">{lookupError}</p>}
            {lookupUser && (
              <div className="border border-slate-200 rounded-xl p-4">
                <p className="font-semibold text-slate-800">{lookupUser.name} <span className="text-slate-400 font-normal">#{lookupUser.user_id}</span></p>
                <p className="text-sm text-slate-500">{lookupUser.email}{lookupUser.phone ? ` · ${lookupUser.phone}` : ''}</p>
                <div className="flex flex-wrap items-center gap-2 mt-3">
                  <span className="text-sm text-slate-600">Role:</span>
                  <select value={newRole} onChange={(e) => { setNewRole(e.target.value); setConfirmSelfDemote(false); }}
                    className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm outline-none">
                    {VALID_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <ActionButton busy={pending.role} onClick={applyRole}>Update role</ActionButton>
                </div>
                {confirmSelfDemote && (
                  <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm">
                    <p className="text-slate-700 mb-2">This changes your own role and may remove your admin access. Continue?</p>
                    <div className="flex gap-2">
                      <button onClick={() => setConfirmSelfDemote(false)} className="px-3 py-1 text-xs bg-white border border-slate-300 rounded-lg">Keep admin</button>
                      <button onClick={applyRole} className="px-3 py-1 text-xs bg-red-600 text-white rounded-lg">Confirm change</button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Section>
        )}

        {tab === 'barbers' && (
          <Section title="Barbers">
            <form onSubmit={submitBarber} className="grid sm:grid-cols-3 gap-2 mb-4">
              <input value={barberForm.name} onChange={(e) => setBarberForm({ ...barberForm, name: e.target.value })} placeholder="Name *" required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={barberForm.specialization} onChange={(e) => setBarberForm({ ...barberForm, specialization: e.target.value })} placeholder="Specialization"
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={barberForm.phone} onChange={(e) => setBarberForm({ ...barberForm, phone: e.target.value })} placeholder="Phone"
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={barberForm.experience_years} onChange={(e) => setBarberForm({ ...barberForm, experience_years: e.target.value })} placeholder="Experience (yrs)" type="number" min="0"
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <select value={barberForm.availability_status} onChange={(e) => setBarberForm({ ...barberForm, availability_status: e.target.value })}
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none">
                <option value="available">available</option>
                <option value="busy">busy</option>
                <option value="inactive">inactive</option>
              </select>
              <button type="submit" disabled={pending['barber-save']} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
                {pending['barber-save'] ? 'Saving...' : editingBarber ? 'Update barber' : 'Add barber'}
              </button>
            </form>
            {editingBarber && <button onClick={() => { setEditingBarber(null); setBarberForm({ name: '', specialization: '', phone: '', experience_years: '', availability_status: 'available' }); }} className="text-xs text-slate-500 mb-3">Cancel edit</button>}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-100">
                    <th className="py-2 pr-4 font-medium">ID</th>
                    <th className="py-2 pr-4 font-medium">Name</th>
                    <th className="py-2 pr-4 font-medium">Specialization</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {barbers.map((b) => (
                    <tr key={b.barber_id} className="border-b border-slate-50">
                      <td className="py-2 pr-4">#{b.barber_id}</td>
                      <td className="py-2 pr-4 font-medium">{b.name}</td>
                      <td className="py-2 pr-4 text-slate-500">{b.specialization || '—'}</td>
                      <td className="py-2 pr-4 capitalize">{b.availability_status}</td>
                      <td className="py-2">
                        <div className="flex gap-1.5">
                          <ActionButton busy={false} tone="subtle" onClick={() => { setEditingBarber(b.barber_id); setBarberForm({ name: b.name || '', specialization: b.specialization || '', phone: b.phone || '', experience_years: b.experience_years ?? '', availability_status: b.availability_status || 'available' }); }}>Edit</ActionButton>
                          {confirmDelete === `barber-${b.barber_id}` ? (
                            <>
                              <ActionButton busy={pending[`del-barber-${b.barber_id}`]} tone="danger" onClick={() => { runAction(`del-barber-${b.barber_id}`, () => api.delete(`/barbers/${b.barber_id}`), 'Barber deleted.'); setConfirmDelete(null); }}>Confirm</ActionButton>
                              <ActionButton busy={false} tone="subtle" onClick={() => setConfirmDelete(null)}>Keep</ActionButton>
                            </>
                          ) : (
                            <ActionButton busy={false} tone="danger" onClick={() => setConfirmDelete(`barber-${b.barber_id}`)}>Delete</ActionButton>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {tab === 'services' && (
          <Section title="Services">
            <p className="text-xs text-slate-400 mb-3">Note: the services list shows active services only; deactivated rows leave this list.</p>
            <form onSubmit={submitService} className="grid sm:grid-cols-3 gap-2 mb-4">
              <input value={svcForm.service_name} onChange={(e) => setSvcForm({ ...svcForm, service_name: e.target.value })} placeholder="Service name *" required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={svcForm.duration_minutes} onChange={(e) => setSvcForm({ ...svcForm, duration_minutes: e.target.value })} placeholder="Duration (min) *" type="number" min="1" required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={svcForm.price} onChange={(e) => setSvcForm({ ...svcForm, price: e.target.value })} placeholder="Price *" type="number" min="0" step="0.01" required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={svcForm.description} onChange={(e) => setSvcForm({ ...svcForm, description: e.target.value })} placeholder="Description"
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
              <select value={svcForm.status} onChange={(e) => setSvcForm({ ...svcForm, status: e.target.value })}
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none">
                <option value="active">active</option>
                <option value="inactive">inactive</option>
              </select>
              <button type="submit" disabled={pending['svc-save']} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
                {pending['svc-save'] ? 'Saving...' : editingSvc ? 'Update service' : 'Add service'}
              </button>
            </form>
            {editingSvc && <button onClick={() => { setEditingSvc(null); setSvcForm({ service_name: '', description: '', duration_minutes: '', price: '', status: 'active' }); }} className="text-xs text-slate-500 mb-3">Cancel edit</button>}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-100">
                    <th className="py-2 pr-4 font-medium">ID</th>
                    <th className="py-2 pr-4 font-medium">Name</th>
                    <th className="py-2 pr-4 font-medium">Duration</th>
                    <th className="py-2 pr-4 font-medium">Price</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {services.map((s) => (
                    <tr key={s.service_id} className="border-b border-slate-50">
                      <td className="py-2 pr-4">#{s.service_id}</td>
                      <td className="py-2 pr-4 font-medium">{s.service_name}</td>
                      <td className="py-2 pr-4 text-slate-500">{s.duration_minutes} min</td>
                      <td className="py-2 pr-4 text-slate-500">₹{s.price}</td>
                      <td className="py-2 pr-4">{s.status}</td>
                      <td className="py-2">
                        <div className="flex gap-1.5">
                          <ActionButton busy={false} tone="subtle" onClick={() => { setEditingSvc(s.service_id); setSvcForm({ service_name: s.service_name || '', description: s.description || '', duration_minutes: s.duration_minutes ?? '', price: s.price ?? '', status: s.status || 'active' }); }}>Edit</ActionButton>
                          {confirmDelete === `svc-${s.service_id}` ? (
                            <>
                              <ActionButton busy={pending[`del-svc-${s.service_id}`]} tone="danger" onClick={() => { runAction(`del-svc-${s.service_id}`, () => api.delete(`/services/${s.service_id}`), 'Service deleted.'); setConfirmDelete(null); }}>Confirm</ActionButton>
                              <ActionButton busy={false} tone="subtle" onClick={() => setConfirmDelete(null)}>Keep</ActionButton>
                            </>
                          ) : (
                            <ActionButton busy={false} tone="danger" onClick={() => setConfirmDelete(`svc-${s.service_id}`)}>Delete</ActionButton>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {tab === 'availability' && (
          <Section title="Availability">
            <form onSubmit={submitAvailability} className="grid sm:grid-cols-5 gap-2 mb-4">
              <select value={availForm.barber_id} onChange={(e) => setAvailForm({ ...availForm, barber_id: e.target.value })} required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none">
                <option value="">Barber *</option>
                {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
              </select>
              <input type="date" value={availForm.date} min={today} onChange={(e) => setAvailForm({ ...availForm, date: e.target.value })} required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none" />
              <input type="time" value={availForm.start_time} onChange={(e) => setAvailForm({ ...availForm, start_time: e.target.value })} required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none" />
              <input type="time" value={availForm.end_time} onChange={(e) => setAvailForm({ ...availForm, end_time: e.target.value })} required
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm outline-none" />
              <button type="submit" disabled={pending['avail-save']} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
                {pending['avail-save'] ? 'Adding...' : 'Add window'}
              </button>
            </form>
            {availability.length === 0 ? (
              <EmptyState title="No availability windows for today." />
            ) : (
              <div className="space-y-2">
                {availability.map((v) => (
                  <div key={v.availability_id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg text-sm">
                    <span className="font-medium">{barberOf(v.barber_id)?.name || `Barber #${v.barber_id}`}</span>
                    <span className="text-slate-500">{String(v.date).slice(0, 10)} · {fmtTime(v.start_time)} – {fmtTime(v.end_time)}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs capitalize ${statusStyle(v.status)}`}>{v.status}</span>
                    {confirmDelete === `avail-${v.availability_id}` ? (
                      <span className="ml-auto flex gap-1.5">
                        <ActionButton busy={pending[`del-avail-${v.availability_id}`]} tone="danger" onClick={() => { runAction(`del-avail-${v.availability_id}`, () => api.delete(`/availability/${v.availability_id}`), 'Availability removed.'); setConfirmDelete(null); }}>Confirm</ActionButton>
                        <ActionButton busy={false} tone="subtle" onClick={() => setConfirmDelete(null)}>Keep</ActionButton>
                      </span>
                    ) : (
                      <button onClick={() => setConfirmDelete(`avail-${v.availability_id}`)} className="ml-auto text-xs text-red-600 hover:text-red-800 font-medium">Delete</button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === 'notifications' && (
          <Section title="Notifications">
            {notifications.length === 0 ? (
              <EmptyState title="No notifications recorded." />
            ) : (
              <div className="space-y-2">
                {notifications.slice(0, 50).map((n) => (
                  <div key={n.notification_id} className="p-3 bg-slate-50 rounded-lg text-sm">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">{String(n.type || '—').replace(/_/g, ' ')}</span>
                      <span className="px-2 py-0.5 rounded-full text-xs bg-slate-200 text-slate-600">{String(n.channel || '—').toUpperCase()}</span>
                      <span className="ml-auto text-xs text-slate-400">{n.created_at ? String(n.created_at).slice(0, 16).replace('T', ' ') : ''}</span>
                    </div>
                    <p className="text-xs text-slate-500 mt-1">
                      User #{n.user_id} · Status: {n.status || '—'}
                      {n.attempts != null ? ` · Attempts: ${n.attempts}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}
      </main>
    </div>
  );
}

function OverviewTab({ todaysAppointments, queue, barbers, services, notifications }) {
  const count = (list, key, values) => list.filter((x) => values.includes(String(x[key] || '').toLowerCase())).length;
  const cards = [
    { label: "Today's Appointments", value: todaysAppointments.length },
    { label: 'Waiting', value: count(queue, 'status', ['waiting']) },
    { label: 'Serving', value: count(queue, 'status', ['serving', 'in_progress']) },
    { label: 'Completed Today', value: count(todaysAppointments, 'status', ['completed']) },
    { label: 'Barbers', value: barbers.length },
    { label: 'Active Services', value: services.length },
    { label: 'Notifications', value: notifications.length },
    { label: 'Cancelled / No-show', value: count(todaysAppointments, 'status', ['cancelled', 'no_show']) },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div key={c.label} className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <p className="text-slate-500 text-sm">{c.label}</p>
          <p className="text-3xl font-bold text-slate-800 mt-1">{c.value}</p>
        </div>
      ))}
    </div>
  );
}
