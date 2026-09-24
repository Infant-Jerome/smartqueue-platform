import Card from '../ui/Card';
import { EmptyState } from '../States';

/** Notification history (admin scope). Read-only, same endpoint as before. */
export default function AdminNotifications({ items }) {
  return (
    <Card>
      <h2 className="sq-h2 mb-4">Notifications</h2>
      {items.length === 0 ? (
        <EmptyState title="No notifications recorded." />
      ) : (
        <div className="space-y-2">
          {items.slice(0, 50).map((n) => (
            <div key={n.notification_id} className="p-3 bg-[var(--sq-surface-muted)] rounded-[var(--sq-radius-lg)] text-sm">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium">{String(n.type || '—').replace(/_/g, ' ')}</span>
                <span className="px-2 py-0.5 rounded-full text-xs bg-[var(--sq-border)] text-[var(--sq-text-muted)]">
                  {String(n.channel || '—').toUpperCase()}
                </span>
                <span className="ml-auto sq-caption text-[var(--sq-text-subtle)] sq-tnum">
                  {n.created_at ? String(n.created_at).slice(0, 16).replace('T', ' ') : ''}
                </span>
              </div>
              <p className="sq-caption text-[var(--sq-text-muted)] mt-1 sq-tnum">
                User #{n.user_id} · Status: {n.status || '—'}
                {n.attempts != null ? ` · Attempts: ${n.attempts}` : ''}
              </p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
