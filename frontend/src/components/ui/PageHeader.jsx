/** PageHeader — responsive title row with optional icon + actions. */
export default function PageHeader({ title, description, icon, actions }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
      <div className="flex items-start gap-3 min-w-0">
        {icon && (
          <span className="hidden sm:flex w-10 h-10 rounded-[var(--sq-radius-lg)] bg-[var(--sq-primary-soft)] text-[var(--sq-primary)] items-center justify-center shrink-0" aria-hidden="true">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h1 className="sq-h1 text-[var(--sq-text)]">{title}</h1>
          {description && <p className="text-[var(--sq-text-muted)] text-sm mt-1">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
