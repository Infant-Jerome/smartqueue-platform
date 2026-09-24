import { Play, Check } from 'lucide-react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import StatusBadge from '../ui/StatusBadge';
import Field from '../ui/Field';
import Select from '../ui/Select';
import { ConfidenceBadge } from '../QueueStatusCard';
import { EmptyState } from '../States';

const STATUS_OPTIONS = ['All', 'Waiting', 'Serving', 'Completed', 'Cancelled', 'No Show'];

/** Live queue control room. Same endpoints, filters and actions as before. */
export default function AdminQueue({
  queue, barbers, pending,
  statusFilter, setStatusFilter, barberFilter, setBarberFilter,
  barberOf, onServe, onComplete, onSkip, onServeNext,
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <h2 className="sq-h2 mr-auto">Live Queue</h2>
        <Field>
          <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter queue by status" className="!w-auto !min-h-0 py-1.5">
            {STATUS_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
          </Select>
        </Field>
        <Field>
          <Select value={barberFilter} onChange={(e) => setBarberFilter(e.target.value)} aria-label="Filter queue by barber" className="!w-auto !min-h-0 py-1.5">
            <option value="All">All barbers</option>
            {barbers.map((b) => <option key={b.barber_id} value={b.barber_id}>{b.name}</option>)}
          </Select>
        </Field>
      </div>

      {queue.length === 0 ? (
        <EmptyState title="Queue is clear." message="New bookings will appear here in real time." />
      ) : (
        <div className="space-y-2">
          {queue.map((q) => {
            const st = String(q.status).toLowerCase();
            const serving = st === 'serving' || st === 'in_progress';
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
                      Appt #{q.appointment_id} · {barberOf(q.barber_id)?.name || `Barber #${q.barber_id}`}
                    </p>
                    <p className="text-xs text-[var(--sq-text-muted)] sq-tnum">
                      {q.estimated_wait_minutes != null ? `~${q.estimated_wait_minutes} min wait` : 'Calculating…'}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusBadge status={q.status} />
                      {q.confidence && <ConfidenceBadge level={q.confidence} />}
                    </div>
                  </div>
                </div>
                <div className="flex gap-1.5 ml-12 sm:ml-0">
                  {st === 'waiting' && (
                    <Button size="sm" loading={pending[`serve-${q.queue_id}`]} onClick={() => onServe(q.queue_id)} icon={<Play size={13} aria-hidden="true" />}>
                      Serve
                    </Button>
                  )}
                  {serving && (
                    <Button size="sm" tone="success" loading={pending[`complete-${q.queue_id}`]} onClick={() => onComplete(q.queue_id)} icon={<Check size={13} aria-hidden="true" />}>
                      Complete
                    </Button>
                  )}
                  {st === 'waiting' && (
                    <Button size="sm" tone="danger" loading={pending[`skip-${q.queue_id}`]} onClick={() => onSkip(q.queue_id)}>
                      Skip
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-[var(--sq-border)]">
        <h3 className="sq-label text-[var(--sq-text-muted)] mb-2">Serve next per barber</h3>
        <div className="flex flex-wrap gap-2">
          {barbers.map((b) => (
            <Button key={b.barber_id} size="sm" tone="secondary" loading={pending[`next-${b.barber_id}`]} onClick={() => onServeNext(b.barber_id, b.name)}>
              Next: {b.name}
            </Button>
          ))}
        </div>
      </div>
    </Card>
  );
}
