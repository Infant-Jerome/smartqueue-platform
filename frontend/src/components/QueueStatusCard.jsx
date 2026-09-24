import { Users, Timer, Scissors, User, CalendarDays, Activity } from 'lucide-react';
import Card from './ui/Card';
import StatusBadge from './ui/StatusBadge';
import ConfidenceMeter from './ui/ConfidenceMeter';
import { queuePositionOf } from '../utils/format';

/**
 * SAWTE estimate display. Renders backend values verbatim; no client-side
 * wait calculation. Confidence = historical-data availability, not accuracy.
 */
export function ConfidenceBadge({ level }) {
  if (!level) return null;
  return <ConfidenceMeter level={level} compact />;
}

function Stat({ icon, label, value, sub }) {
  return (
    <div className="flex items-center gap-3 min-w-0">
      <span
        className="flex w-9 h-9 rounded-[var(--sq-radius-lg)] bg-[var(--sq-primary-soft)] text-[var(--sq-primary)] items-center justify-center shrink-0"
        aria-hidden="true"
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="sq-caption text-[var(--sq-text-subtle)] uppercase tracking-wide">{label}</p>
        <p className="text-lg font-bold text-[var(--sq-text)] sq-tnum truncate">{value}</p>
        {sub && <p className="sq-caption text-[var(--sq-text-subtle)] truncate">{sub}</p>}
      </div>
    </div>
  );
}

const GUIDANCE = {
  waiting: 'Stay nearby. We’ll keep your queue position updated.',
  serving: 'Your turn is now. Please head to your barber.',
  in_progress: 'Your turn is now. Please head to your barber.',
  completed: 'Your appointment has been completed. Thank you!',
  cancelled: 'Your appointment is no longer active.',
  no_show: 'You were marked as no-show. Please book again if needed.',
};

/**
 * Premium queue hero. All values come from the backend `info` object
 * (my-position response) plus the optional `appointment` record.
 * Nothing is calculated here.
 */
export function QueueStatusCard({ info, appointment, live }) {
  if (!info?.has_queue) return null;

  const position = queuePositionOf(info);
  const serving = info.currently_serving ?? info.current_position;
  const status = String(info.status ?? '').toLowerCase();
  const wait = info.estimated_wait_minutes;
  const ahead = info.people_ahead ?? 0;
  const serviceName =
    appointment?.service?.service_name || appointment?.service?.name;
  const barberName = appointment?.barber?.name;
  const when =
    appointment?.appointment_date != null || appointment?.start_time != null
      ? `${String(appointment?.appointment_date ?? '').slice(0, 10)}${appointment?.start_time ? ` · ${String(appointment.start_time).slice(0, 5)}` : ''}`
      : null;

  return (
    <Card padding="lg" className="mb-6 overflow-hidden">
      {/* Top row: live indicator + status */}
      <div className="flex items-center justify-between gap-3 mb-5">
        {live === undefined ? (
          <span />
        ) : (
          <span
            className={`inline-flex items-center gap-1.5 text-xs font-semibold ${live ? 'text-[var(--sq-success)]' : 'text-[var(--sq-text-subtle)]'}`}
          >
            <span className="relative flex h-2 w-2" aria-hidden="true">
              {live && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--sq-success)] opacity-60" />
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${live ? 'bg-[var(--sq-success)]' : 'bg-[var(--sq-border)]'}`} />
            </span>
            {live ? 'Live queue' : 'Updating'}
          </span>
        )}
        <StatusBadge status={info.status} />
      </div>

      {/* Token hero */}
      <div className="flex flex-col sm:flex-row sm:items-end gap-5 sm:gap-8">
        <div className="min-w-0">
          <p className="sq-caption text-[var(--sq-text-subtle)] uppercase tracking-widest">Your token</p>
          <p className="sq-display text-[var(--sq-primary)] sq-tnum leading-none mt-1">
            #{position ?? '—'}
          </p>
        </div>
        <div className="sm:pb-1">
          <p className="sq-caption text-[var(--sq-text-subtle)] uppercase tracking-widest">Currently serving</p>
          <p className="text-3xl font-extrabold text-[var(--sq-text)] sq-tnum mt-1">
            {serving != null ? `#${serving}` : '—'}
          </p>
        </div>
      </div>

      {/* Position visualization: serving → you (endpoints only, no fake members) */}
      {serving != null && position != null && (
        <div className="mt-5" aria-hidden="true">
          <div className="relative h-1.5 rounded-full bg-[var(--sq-surface-muted)]">
            <div className="absolute inset-y-0 left-0 right-0 rounded-full bg-gradient-to-r from-[var(--sq-success)] via-[var(--sq-primary)] to-[var(--sq-accent)] opacity-80" />
            <span className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-0 w-3.5 h-3.5 rounded-full bg-[var(--sq-surface)] border-[3px] border-[var(--sq-success)]" />
            <span className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-0 w-3.5 h-3.5 rounded-full bg-[var(--sq-surface)] border-[3px] border-[var(--sq-accent)]" />
          </div>
          <div className="flex justify-between mt-1.5">
            <span className="sq-caption text-[var(--sq-text-subtle)] sq-tnum">#{serving} serving</span>
            <span className="sq-caption text-[var(--sq-text-subtle)] sq-tnum">#{position} you</span>
          </div>
        </div>
      )}

      {/* Key stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6 pt-5 border-t border-[var(--sq-border)]">
        <Stat
          icon={<Users size={18} />}
          label="People ahead"
          value={ahead === 0 ? 'You’re next' : `${ahead} ${ahead === 1 ? 'person' : 'people'} ahead`}
        />
        <Stat
          icon={<Timer size={18} />}
          label="Estimated wait"
          value={wait != null ? `${wait} min` : 'Calculating…'}
          sub={wait != null ? 'From live queue data' : undefined}
        />
      </div>

      {/* Context row */}
      {(serviceName || barberName || when) && (
        <div className="flex flex-wrap gap-x-5 gap-y-2 mt-5 pt-4 border-t border-[var(--sq-border)]">
          {serviceName && (
            <span className="inline-flex items-center gap-1.5 text-sm text-[var(--sq-text-muted)]">
              <Scissors size={15} aria-hidden="true" /> {serviceName}
            </span>
          )}
          {barberName && (
            <span className="inline-flex items-center gap-1.5 text-sm text-[var(--sq-text-muted)]">
              <User size={15} aria-hidden="true" /> {barberName}
            </span>
          )}
          {when && (
            <span className="inline-flex items-center gap-1.5 text-sm text-[var(--sq-text-muted)]">
              <CalendarDays size={15} aria-hidden="true" /> {when}
            </span>
          )}
        </div>
      )}

      {/* Confidence + guidance */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 mt-5 pt-4 border-t border-[var(--sq-border)]">
        <ConfidenceMeter level={info.confidence} />
        {GUIDANCE[status] && (
          <p className="sq-body-sm text-[var(--sq-text-muted)] sm:ml-auto flex items-center gap-1.5">
            <Activity size={14} aria-hidden="true" /> {GUIDANCE[status]}
          </p>
        )}
      </div>
    </Card>
  );
}
