/** Canonical backend field access with legacy fallbacks (read-only transition). */
export const serviceId = (s) => s?.service_id ?? s?.id;
export const serviceName = (s) => s?.service_name ?? s?.name ?? 'Service';
export const serviceDuration = (s) => s?.duration_minutes ?? s?.duration;

export const barberId = (b) => b?.barber_id ?? b?.id;
export const barberStatus = (b) => b?.availability_status ?? b?.status ?? 'unknown';

export const appointmentId = (a) => a?.appointment_id ?? a?.id;
export const queuePositionOf = (q) => q?.queue_position ?? q?.queue_number;
export const queueIdOf = (q) => q?.queue_id ?? q?.id;

export function fmtTime(t) {
  if (!t) return '—';
  return String(t).slice(0, 5);
}

export function fmtDate(d) {
  if (!d) return '—';
  return String(d).slice(0, 10);
}

const STATUS_STYLES = {
  booked: 'bg-blue-100 text-blue-700',
  confirmed: 'bg-indigo-100 text-indigo-700',
  waiting: 'bg-yellow-100 text-yellow-700',
  serving: 'bg-yellow-100 text-yellow-700',
  in_progress: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-700',
  no_show: 'bg-slate-200 text-slate-600',
};

export function statusStyle(status) {
  return STATUS_STYLES[String(status || '').toLowerCase()] || 'bg-slate-100 text-slate-600';
}

export function prettyStatus(status) {
  return String(status || '—').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const CONFIDENCE_HELP = {
  LOW: 'Limited historical service data',
  MEDIUM: 'Moderate historical service data',
  HIGH: 'More historical service data available',
};

export function confidenceHelp(level) {
  return CONFIDENCE_HELP[String(level || '').toUpperCase()] || null;
}
