import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { CalendarPlus, ClipboardList, Users, Sparkles, Bell, ArrowRight } from 'lucide-react';
import api from '../services/api';
import Navbar from '../components/Navbar';
import { useAuth } from '../context/AuthContext';
import { appointmentId } from '../utils/format';
import { QueueStatusCard } from '../components/QueueStatusCard';
import { LoadingState, EmptyState } from '../components/States';
import { AppointmentCard } from '../components/AppointmentCard';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import PageHeader from '../components/ui/PageHeader';

const UPCOMING_STATUSES = new Set(['booked', 'confirmed', 'waiting']);

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

const QUICK_ACTIONS = [
  { to: '/book', title: 'Book Appointment', desc: 'Schedule a new visit', icon: <CalendarPlus size={20} aria-hidden="true" />, accent: true },
  { to: '/queue', title: 'Live Queue', desc: 'Check your token & wait', icon: <Users size={20} aria-hidden="true" /> },
  { to: '/appointments', title: 'My Appointments', desc: 'View and manage bookings', icon: <ClipboardList size={20} aria-hidden="true" /> },
  { to: '/services', title: 'Services', desc: 'Browse treatments & prices', icon: <Sparkles size={20} aria-hidden="true" /> },
];

export default function Dashboard() {
  const { user } = useAuth();
  const [queueInfo, setQueueInfo] = useState(null);
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Same endpoints as before: my-position + own appointments. No new requests,
  // no WebSocket here (the Queue page owns realtime); backend stays authoritative.
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
    UPCOMING_STATUSES.has(String(a.status || '').toLowerCase())
  );

  if (loading) {
    return (
      <><Navbar />
      <div className="max-w-5xl mx-auto px-4 py-8">
        <PageHeader title={`${greeting()}${firstName(user) ? `, ${firstName(user)}` : ''}`} description="Loading your overview…" />
        <LoadingState message="Loading dashboard..." />
      </div>
      </>
    );
  }

  return (
    <><Navbar />
    <div className="max-w-5xl mx-auto px-4 py-8">
      <PageHeader
        title={`${greeting()}${firstName(user) ? `, ${firstName(user)}` : ''}`}
        description={
          queueInfo?.has_queue
            ? 'You have an active visit — here’s where things stand.'
            : upcoming
              ? 'Your next visit is coming up.'
              : 'Ready when you are — book your next visit.'
        }
        actions={
          <Link to="/notifications" aria-label="Notifications">
            <Button tone="secondary" size="sm" icon={<Bell size={16} aria-hidden="true" />}>
              Notifications
            </Button>
          </Link>
        }
      />

      {error && (
        <div className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{error}</div>
      )}

      {/* P0 — active queue hero (backend values, rendered by QueueStatusCard) */}
      {queueInfo?.has_queue ? (
        <section aria-label="Active visit">
          <QueueStatusCard info={queueInfo} />
          <div className="flex justify-end -mt-2 mb-6">
            <Link to="/queue" className="inline-flex items-center gap-1 text-sm font-medium text-[var(--sq-primary)] hover:underline">
              View Live Queue <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
        </section>
      ) : (
        <Card padding="lg" className="mb-6 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex w-12 h-12 rounded-[var(--sq-radius-xl)] bg-[var(--sq-accent-soft)] text-[var(--sq-accent)] items-center justify-center shrink-0" aria-hidden="true">
            <CalendarPlus size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="sq-h2">No active visit</h2>
            <p className="sq-body-sm text-[var(--sq-text-muted)] mt-0.5">Book your next visit when you’re ready — it takes under a minute.</p>
          </div>
          <Link to="/book" className="shrink-0">
            <Button>Book Appointment</Button>
          </Link>
        </Card>
      )}

      {/* P1 — upcoming appointment */}
      {upcoming && (
        <section aria-label="Upcoming appointment" className="mb-6">
          <h2 className="sq-h3 text-[var(--sq-text-subtle)] uppercase tracking-wide mb-3">Up next</h2>
          <AppointmentCard appointment={upcoming} />
        </section>
      )}

      {/* P1 — quick actions */}
      <section aria-label="Quick actions" className="mb-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {QUICK_ACTIONS.map((a) => (
            <Link
              key={a.to + a.title}
              to={a.to}
              className={`rounded-[var(--sq-radius-2xl)] border p-4 transition-shadow duration-[var(--sq-transition-normal)] hover:shadow-[var(--sq-shadow-md)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)] ${
                a.accent
                  ? 'bg-[var(--sq-primary)] border-[var(--sq-primary)] text-white'
                  : 'bg-[var(--sq-surface)] border-[var(--sq-border)]'
              }`}
            >
              <span className={a.accent ? 'text-white/90' : 'text-[var(--sq-primary)]'} aria-hidden="true">{a.icon}</span>
              <span className={`block font-semibold mt-2 text-sm ${a.accent ? 'text-white' : 'text-[var(--sq-text)]'}`}>{a.title}</span>
              <span className={`block text-xs mt-0.5 ${a.accent ? 'text-white/75' : 'text-[var(--sq-text-muted)]'}`}>{a.desc}</span>
            </Link>
          ))}
        </div>
      </section>

      {/* P2 — recent appointments */}
      {appointments.length > 0 && (
        <section aria-label="Recent appointments">
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h2 className="sq-h2">Recent visits</h2>
              <Link to="/appointments" className="text-sm text-[var(--sq-primary)] hover:underline font-medium">View all</Link>
            </div>
            <div className="space-y-2">
              {appointments.map((appt) => (
                <Link
                  key={appointmentId(appt)}
                  to="/appointments"
                  className="flex items-center justify-between gap-3 p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)] hover:shadow-[var(--sq-shadow-sm)] transition-shadow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)]"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-[var(--sq-text)] text-sm truncate">
                      {appt.service?.service_name || appt.service?.name || 'Service'} with {appt.barber?.name || 'Barber'}
                    </p>
                    <p className="text-xs text-[var(--sq-text-muted)] sq-tnum">
                      {String(appt.appointment_date).slice(0, 10)} · {String(appt.start_time || appt.appointment_time || '').slice(0, 5)}
                    </p>
                  </div>
                  <ArrowRight size={16} className="text-[var(--sq-text-subtle)] shrink-0" aria-hidden="true" />
                </Link>
              ))}
            </div>
          </Card>
        </section>
      )}

      {appointments.length === 0 && !queueInfo?.has_queue && !error && (
        <EmptyState
          title="Nothing here yet"
          message="Your bookings and visits will appear on this dashboard."
        />
      )}
    </div>
    </>
  );
}
