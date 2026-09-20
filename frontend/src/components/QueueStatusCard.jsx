import { confidenceHelp, queuePositionOf } from '../utils/format';

/**
 * SAWTE estimate display. Renders backend values verbatim; no client-side
 * wait calculation. Confidence = historical-data availability, not accuracy.
 */
export function ConfidenceBadge({ level }) {
  if (!level) return null;
  const upper = String(level).toUpperCase();
  const style =
    upper === 'HIGH' ? 'bg-green-100 text-green-700' :
    upper === 'MEDIUM' ? 'bg-yellow-100 text-yellow-700' :
    'bg-slate-200 text-slate-600';
  return (
    <span className={`px-3 py-1 rounded-full text-xs font-medium ${style}`} title={confidenceHelp(upper) || ''}>
      {upper}
    </span>
  );
}

export function QueueStatusCard({ info, compact = false }) {
  if (!info?.has_queue) return null;
  const position = queuePositionOf(info);
  return (
    <div className={`bg-gradient-to-r from-blue-600 to-blue-700 rounded-2xl text-white ${compact ? 'p-6' : 'p-8'} mb-6`}>
      <div className="text-center mb-4">
        <p className="text-blue-200 text-sm mb-1">Your Queue Position</p>
        <p className={`${compact ? 'text-4xl' : 'text-6xl'} font-bold`}>#{position ?? '—'}</p>
      </div>
      <div className={`grid grid-cols-2 ${compact ? '' : 'md:grid-cols-4'} gap-4 text-center`}>
        <div>
          <p className="text-blue-200 text-sm">People Ahead</p>
          <p className="text-2xl font-bold">{info.people_ahead ?? 0}</p>
        </div>
        <div>
          <p className="text-blue-200 text-sm">Estimated Wait</p>
          <p className="text-2xl font-bold">
            {info.estimated_wait_minutes != null ? `${info.estimated_wait_minutes} min` : '—'}
          </p>
        </div>
        {!compact && (
          <>
            <div>
              <p className="text-blue-200 text-sm">Confidence</p>
              <p className="text-2xl font-bold">{info.confidence ? String(info.confidence).toUpperCase() : '—'}</p>
            </div>
            <div>
              <p className="text-blue-200 text-sm">Status</p>
              <p className="text-2xl font-bold capitalize">{info.status ?? '—'}</p>
            </div>
          </>
        )}
      </div>
      {info.confidence && (
        <p className="text-center text-blue-200 text-xs mt-4">
          Confidence reflects available service-history data, not prediction accuracy.
        </p>
      )}
    </div>
  );
}
