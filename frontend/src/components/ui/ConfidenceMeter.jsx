import { confidenceHelp } from '../../utils/format';

/**
 * ConfidenceMeter — visualizes the backend SAWTE confidence level.
 * Confidence reflects historical-data availability, never accuracy.
 * Explanations come only from confidenceHelp() in utils/format.js.
 */
const LEVELS = ['LOW', 'MEDIUM', 'HIGH'];

export default function ConfidenceMeter({ level, compact }) {
  if (!level) return null;
  const upper = String(level).toUpperCase();
  const filled = LEVELS.indexOf(upper) + 1;
  const help = confidenceHelp(upper);

  return (
    <div className={compact ? '' : 'flex flex-col items-center gap-1.5'}>
      <div className="flex items-center gap-1.5" role="img" aria-label={`Estimate confidence: ${upper}${help ? `. ${help}` : ''}`}>
        <div className="flex gap-1" aria-hidden="true">
          {LEVELS.map((l, i) => (
            <span
              key={l}
              className={`h-1.5 w-6 rounded-full ${i < filled ? 'bg-[var(--sq-accent)]' : 'bg-[var(--sq-border)]'}`}
            />
          ))}
        </div>
        <span className="text-xs font-semibold tracking-wide text-[var(--sq-text-muted)]">{upper}</span>
      </div>
      {help && !compact && (
        <p className="text-[var(--sq-text-subtle)] text-xs">{help}</p>
      )}
    </div>
  );
}
