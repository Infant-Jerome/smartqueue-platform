import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  LayoutDashboard, ListOrdered, CalendarCheck, Users, Scissors,
  Sparkles, Clock, Bell, ShieldCheck,
} from 'lucide-react';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { LoadingState, ErrorState } from '../components/States';
import PageHeader from '../components/ui/PageHeader';
import { useQueueSocket } from '../hooks/useQueueSocket';
import AdminOverview from '../components/admin/AdminOverview';
import AdminQueue from '../components/admin/AdminQueue';
import AdminAppointments from '../components/admin/AdminAppointments';
import AdminUsers from '../components/admin/AdminUsers';
import AdminBarbers from '../components/admin/AdminBarbers';
import AdminServices from '../components/admin/AdminServices';
import AdminAvailability from '../components/admin/AdminAvailability';
import AdminNotifications from '../components/admin/AdminNotifications';

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function displayDate() {
  return new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

/**
 * Admin control center (Phase 9 Step 8 — presentation redesign only).
 * All endpoints, payloads, filters, confirm flows, role protection and the
 * single WebSocket subscription behave exactly as before.
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
    if (queueStatusFilter !== 'All') rows = rows.filter((q) => String(q.status).toLowerCase() === queueStatusFilter.toLowerCase().replace(' ', '_'));
    if (queueBarberFilter !== 'All') rows = rows.filter((q) => q.barber_id === Number(queueBarberFilter));
    return rows;
  }, [queue, queueStatusFilter, queueBarberFilter]);

  const filteredAppts = useMemo(() => {
    let rows = [...todaysAppointments];
    if (apptStatusFilter !== 'All') rows = rows.filter((a) => String(a.status).toLowerCase() === apptStatusFilter.toLowerCase().replace(' ', '_'));
    if (apptBarberFilter !== 'All') rows = rows.filter((a) => a.barber_id === Number(apptBarberFilter));
    return rows;
  }, [todaysAppointments, apptStatusFilter, apptBarberFilter]);

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

  const startEditBarber = (b) => {
    setEditingBarber(b.barber_id);
    setBarberForm({
      name: b.name || '',
      specialization: b.specialization || '',
      phone: b.phone || '',
      experience_years: b.experience_years ?? '',
      availability_status: b.availability_status || 'available',
    });
  };

  const startEditService = (s) => {
    setEditingSvc(s.service_id);
    setSvcForm({
      service_name: s.service_name || '',
      description: s.description || '',
      duration_minutes: s.duration_minutes ?? '',
      price: s.price ?? '',
      status: s.status || 'active',
    });
  };

  const cancelEditForms = () => {
    setEditingSvc(null);
    setEditingBarber(null);
    setSvcForm({ service_name: '', description: '', duration_minutes: '', price: '', status: 'active' });
    setBarberForm({ name: '', specialization: '', phone: '', experience_years: '', availability_status: 'available' });
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
    { id: 'overview', label: 'Overview', icon: <LayoutDashboard size={15} aria-hidden="true" /> },
    { id: 'queue', label: 'Queue', icon: <ListOrdered size={15} aria-hidden="true" /> },
    { id: 'appointments', label: 'Appointments', icon: <CalendarCheck size={15} aria-hidden="true" /> },
    { id: 'users', label: 'Users', icon: <Users size={15} aria-hidden="true" /> },
    { id: 'barbers', label: 'Barbers', icon: <Scissors size={15} aria-hidden="true" /> },
    { id: 'services', label: 'Services', icon: <Sparkles size={15} aria-hidden="true" /> },
    { id: 'availability', label: 'Availability', icon: <Clock size={15} aria-hidden="true" /> },
    { id: 'notifications', label: 'Notifications', icon: <Bell size={15} aria-hidden="true" /> },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader
          title="Admin Control Center"
          description={`Manage your barbershop operations, staff, services, and queue. · ${displayDate()}${user?.name ? ` · ${user.name}` : ''}`}
          icon={<ShieldCheck size={20} aria-hidden="true" />}
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

        {error && <div className="mb-4"><ErrorState message={error} onRetry={fetchAll} /></div>}
        {actionError && <div className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{actionError}</div>}
        {notice && <div className="mb-4 p-3 bg-[var(--sq-success-soft)] border border-[#bbf7d0] rounded-[var(--sq-radius-lg)] text-[var(--sq-success)] text-sm">{notice}</div>}

        <nav aria-label="Admin sections" className="flex gap-2 mb-6 overflow-x-auto pb-1 -mx-px">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? 'page' : undefined}
              className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-[var(--sq-radius-lg)] text-sm font-medium whitespace-nowrap transition-colors duration-[var(--sq-transition-fast)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)] ${
                tab === t.id
                  ? 'bg-[var(--sq-primary)] text-white shadow-[var(--sq-shadow-sm)]'
                  : 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)] hover:bg-[var(--sq-border)]'
              }`}
            >
              {t.icon}{t.label}
            </button>
          ))}
        </nav>

        {tab === 'overview' && (
          <AdminOverview
            todaysAppointments={todaysAppointments}
            queue={queue}
            barbers={barbers}
            services={services}
            notifications={notifications}
          />
        )}

        {tab === 'queue' && (
          <AdminQueue
            queue={filteredQueue}
            barbers={barbers}
            pending={pending}
            statusFilter={queueStatusFilter}
            setStatusFilter={setQueueStatusFilter}
            barberFilter={queueBarberFilter}
            setBarberFilter={setQueueBarberFilter}
            barberOf={barberOf}
            onServe={(qid) => runAction(`serve-${qid}`, () => api.post(`/queue/${qid}/serve`), 'Customer is being served.')}
            onComplete={(qid) => runAction(`complete-${qid}`, () => api.post(`/queue/${qid}/complete`), 'Service completed.')}
            onSkip={(qid) => runAction(`skip-${qid}`, () => api.post(`/queue/${qid}/skip`), 'Marked as no-show.')}
            onServeNext={(bid, name) => runAction(`next-${bid}`, () => api.post('/queue/serve-next', { barber_id: bid }), `Serving next for ${name}.`)}
          />
        )}

        {tab === 'appointments' && (
          <AdminAppointments
            rows={filteredAppts}
            barbers={barbers}
            pending={pending}
            statusFilter={apptStatusFilter}
            setStatusFilter={setApptStatusFilter}
            barberFilter={apptBarberFilter}
            setBarberFilter={setApptBarberFilter}
            barberOf={barberOf}
            serviceOf={serviceOf}
            onCancel={(aid) => runAction(`cancel-${aid}`, () => api.delete(`/appointments/${aid}`), 'Appointment cancelled.')}
          />
        )}

        {tab === 'users' && (
          <AdminUsers
            lookupId={lookupId}
            setLookupId={setLookupId}
            lookupUser={lookupUser}
            lookupError={lookupError}
            newRole={newRole}
            setNewRole={setNewRole}
            confirmSelfDemote={confirmSelfDemote}
            setConfirmSelfDemote={setConfirmSelfDemote}
            pendingRole={pending.role}
            onLookup={lookup}
            onApplyRole={applyRole}
          />
        )}

        {tab === 'barbers' && (
          <AdminBarbers
            barbers={barbers}
            form={barberForm}
            setForm={setBarberForm}
            editingId={editingBarber}
            pendingSave={pending['barber-save']}
            onSubmit={submitBarber}
            onCancelEdit={() => { setEditingBarber(null); setBarberForm({ name: '', specialization: '', phone: '', experience_years: '', availability_status: 'available' }); }}
            onEdit={startEditBarber}
            deleteTarget={confirmDelete?.kind === 'barber' ? confirmDelete.row : null}
            setDeleteTarget={(row) => setConfirmDelete(row ? { kind: 'barber', row } : null)}
            pendingDelete={(id) => pending[`del-barber-${id}`]}
            onDelete={(id) => runAction(`del-barber-${id}`, () => api.delete(`/barbers/${id}`), 'Barber deleted.').then(() => setConfirmDelete(null))}
          />
        )}

        {tab === 'services' && (
          <AdminServices
            services={services}
            form={svcForm}
            setForm={setSvcForm}
            editingId={editingSvc}
            pendingSave={pending['svc-save']}
            onSubmit={submitService}
            onCancelEdit={cancelEditForms}
            onEdit={startEditService}
            deleteTarget={confirmDelete?.kind === 'svc' ? confirmDelete.row : null}
            setDeleteTarget={(row) => setConfirmDelete(row ? { kind: 'svc', row } : null)}
            pendingDelete={(id) => pending[`del-svc-${id}`]}
            onDelete={(id) => runAction(`del-svc-${id}`, () => api.delete(`/services/${id}`), 'Service deleted.').then(() => setConfirmDelete(null))}
          />
        )}

        {tab === 'availability' && (
          <AdminAvailability
            windows={availability}
            barbers={barbers}
            form={availForm}
            setForm={setAvailForm}
            pendingSave={pending['avail-save']}
            onSubmit={submitAvailability}
            deleteTarget={confirmDelete?.kind === 'avail' ? confirmDelete.row : null}
            setDeleteTarget={(row) => setConfirmDelete(row ? { kind: 'avail', row } : null)}
            pendingDelete={(id) => pending[`del-avail-${id}`]}
            onDelete={(id) => runAction(`del-avail-${id}`, () => api.delete(`/availability/${id}`), 'Availability removed.').then(() => setConfirmDelete(null))}
            today={today}
          />
        )}

        {tab === 'notifications' && (
          <AdminNotifications items={notifications} />
        )}
      </main>
    </div>
  );
}
