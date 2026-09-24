/** SmartQueue Button primitive — presentation only, no business logic. */
const TONES = {
  primary: 'bg-[var(--sq-primary)] hover:bg-[var(--sq-primary-hover)] active:bg-[var(--sq-primary-active)] text-white',
  secondary: 'bg-[var(--sq-surface-muted)] hover:bg-[var(--sq-border)] text-[var(--sq-text)]',
  accent: 'bg-[var(--sq-accent)] hover:bg-[var(--sq-accent-hover)] text-white',
  danger: 'bg-[var(--sq-danger-soft)] hover:bg-[#fecaca] text-[var(--sq-danger)] border border-[#fca5a5]',
  ghost: 'hover:bg-[var(--sq-surface-muted)] text-[var(--sq-text-muted)]',
  outline: 'border border-[var(--sq-border)] hover:border-[var(--sq-primary)] text-[var(--sq-primary)] bg-[var(--sq-surface)]',
};

const SIZES = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-3 text-sm',
};

export default function Button({
  tone = 'primary',
  size = 'md',
  disabled,
  loading,
  fullWidth,
  icon,
  children,
  className = '',
  ...rest
}) {
  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--sq-radius-lg)] font-medium transition-colors duration-[var(--sq-transition-normal)] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--sq-primary)] min-h-[2.5rem] ${TONES[tone] || TONES.primary} ${SIZES[size] || SIZES.md} ${fullWidth ? 'w-full' : ''} ${className}`}
      {...rest}
    >
      {loading ? (
        <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-current" aria-hidden="true" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
