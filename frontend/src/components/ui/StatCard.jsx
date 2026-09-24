/** StatCard — premium summary card. Display only, no calculations. */
export default function StatCard({ title, value, description, icon, loading }) {
  return (
    <div className="bg-[var(--sq-surface)] rounded-[var(--sq-radius-2xl)] border border-[var(--sq-border)] p-5 transition-shadow duration-[var(--sq-transition-normal)] hover:shadow-[var(--sq-shadow-md)]">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[var(--sq-text-muted)] text-sm">{title}</p>
        {icon && <span className="text-[var(--sq-primary)] shrink-0" aria-hidden="true">{icon}</span>}
      </div>
      {loading ? (
        <div className="h-9 mt-1 rounded-lg bg-[var(--sq-surface-muted)] animate-pulse" aria-label="Loading" />
      ) : (
        <p className="text-3xl font-bold text-[var(--sq-text)] mt-1 sq-tnum">{value}</p>
      )}
      {description && <p className="text-[var(--sq-text-subtle)] text-xs mt-1">{description}</p>}
    </div>
  );
}
