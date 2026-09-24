import { useEffect } from 'react';
import Button from './Button';

/**
 * ConfirmDialog — presentation-only modal. No API calls; the parent owns
 * business logic via onConfirm/onCancel.
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger,
  loading,
  onConfirm,
  onCancel,
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onCancel?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="w-full max-w-md bg-[var(--sq-surface)] rounded-[var(--sq-radius-2xl)] border border-[var(--sq-border)] p-6 shadow-[var(--sq-shadow-lg)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="sq-h2 text-[var(--sq-text)]">{title}</h2>
        {description && <p className="sq-body-sm text-[var(--sq-text-muted)] mt-2">{description}</p>}
        <div className="flex justify-end gap-2 mt-6">
          <Button tone="secondary" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button tone={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
