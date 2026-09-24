import { prettyStatus } from '../../utils/format';

/**
 * StatusBadge — visual treatment for existing SmartQueue statuses.
 * Reuses semantic meaning from utils/format.js; introduces no new statuses.
 * Status is always shown as text (color is never the only indicator).
 */
const STYLES = {
  booked: 'bg-[var(--sq-info-soft)] text-[var(--sq-info)]',
  confirmed: 'bg-[#e0e7ff] text-[#4338ca]',
  waiting: 'bg-[var(--sq-warning-soft)] text-[var(--sq-warning)]',
  serving: 'bg-[var(--sq-warning-soft)] text-[var(--sq-warning)]',
  in_progress: 'bg-[var(--sq-warning-soft)] text-[var(--sq-warning)]',
  completed: 'bg-[var(--sq-success-soft)] text-[var(--sq-success)]',
  cancelled: 'bg-[var(--sq-danger-soft)] text-[var(--sq-danger)]',
  no_show: 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)]',
  available: 'bg-[var(--sq-success-soft)] text-[var(--sq-success)]',
  unavailable: 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)]',
  active: 'bg-[var(--sq-success-soft)] text-[var(--sq-success)]',
  inactive: 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)]',
  off: 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)]',
  busy: 'bg-[var(--sq-warning-soft)] text-[var(--sq-warning)]',
};

export default function StatusBadge({ status, className = '' }) {
  const key = String(status || '').toLowerCase();
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STYLES[key] || 'bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)]'} ${className}`}
    >
      {prettyStatus(status)}
    </span>
  );
}
