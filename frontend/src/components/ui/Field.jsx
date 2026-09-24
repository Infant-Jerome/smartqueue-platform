/** Native label + error/hint wrapper. Presentation only. */
export default function Field({ label, required, error, hint, children }) {
  return (
    <div>
      {label && (
        <label className="block text-[var(--sq-text)] text-[0.8125rem] font-medium mb-1">
          {label}
          {required && <span className="text-[var(--sq-danger)]"> *</span>}
        </label>
      )}
      {children}
      {error ? (
        <p className="text-[var(--sq-danger)] text-xs mt-1" role="alert">{error}</p>
      ) : hint ? (
        <p className="text-[var(--sq-text-subtle)] text-xs mt-1">{hint}</p>
      ) : null}
    </div>
  );
}
