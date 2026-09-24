/** Card primitive — premium surface. No forced hover. */
const PADDING = {
  sm: 'p-4',
  md: 'p-5',
  lg: 'p-6',
};

export default function Card({ children, className = '', padding = 'md', hover }) {
  return (
    <div
      className={`bg-[var(--sq-surface)] rounded-[var(--sq-radius-2xl)] border border-[var(--sq-border)] shadow-[var(--sq-shadow-sm)] ${PADDING[padding] || PADDING.md} ${hover ? 'transition-shadow duration-[var(--sq-transition-normal)] hover:shadow-[var(--sq-shadow-md)]' : ''} ${className}`}
    >
      {children}
    </div>
  );
}
