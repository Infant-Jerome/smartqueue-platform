import { appointmentId, fmtDate, fmtTime, prettyStatus, statusStyle, queuePositionOf } from '../utils/format';

const CANCELLABLE = new Set(['booked', 'confirmed', 'waiting']);

/** Customer appointment row. Cancel is offered only for cancellable statuses. */
export function AppointmentCard({ appointment, onCancel, cancelling }) {
  const id = appointmentId(appointment);
  const canCancel = CANCELLABLE.has(String(appointment.status || '').toLowerCase());

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-slate-800">
            {appointment.service?.service_name || appointment.service?.name || 'Service'}
            {' with '}
            {appointment.barber?.name || 'Barber'}
          </p>
          <p className="text-sm text-slate-500 mt-1">
            {fmtDate(appointment.appointment_date)} · {fmtTime(appointment.start_time)}
            {appointment.end_time ? ` – ${fmtTime(appointment.end_time)}` : ''}
          </p>
          <p className="text-sm text-slate-500 capitalize">
            Booking: {String(appointment.booking_type || 'online').replace(/_/g, ' ')}
            {queuePositionOf(appointment) != null ? ` · Queue #${queuePositionOf(appointment)}` : ''}
          </p>
        </div>
        <span className={`px-3 py-1 rounded-full text-xs font-medium shrink-0 ${statusStyle(appointment.status)}`}>
          {prettyStatus(appointment.status)}
        </span>
      </div>
      {canCancel && onCancel && (
        <button
          onClick={() => onCancel(id)}
          disabled={cancelling}
          className="mt-4 text-sm text-red-600 hover:text-red-800 font-medium disabled:opacity-50"
        >
          {cancelling ? 'Cancelling...' : 'Cancel appointment'}
        </button>
      )}
    </div>
  );
}
